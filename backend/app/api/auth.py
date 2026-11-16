"""Local email/password authentication with opaque, revocable server sessions."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import ssl
import base64
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.database import get_db
from app.models import AuthSession, OAuthLinkChallenge, PasswordResetToken, User
from app.schemas import TravelPreferences

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token as google_id_token

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
SESSION_COOKIE = "gowander_session"
SESSION_TTL = timedelta(days=7)
PASSWORD_RESET_TTL = timedelta(minutes=30)
GOOGLE_STATE_COOKIE = "gowander_google_state"
GOOGLE_NONCE_COOKIE = "gowander_google_nonce"
GOOGLE_VERIFIER_COOKIE = "gowander_google_verifier"
GOOGLE_COOKIE_PATH = "/api/v1/auth/google"
GOOGLE_LINK_STATE_COOKIE = "gowander_google_link_state"
GOOGLE_LINK_NONCE_COOKIE = "gowander_google_link_nonce"
GOOGLE_LINK_VERIFIER_COOKIE = "gowander_google_link_verifier"
GOOGLE_LINK_CHALLENGE_COOKIE = "gowander_google_link_challenge"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
logger = logging.getLogger(__name__)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)


class SignupRequest(Credentials):
    name: str = Field(min_length=1, max_length=100)


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetComplete(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=12, max_length=256)


def _normalize_email(email: str) -> str:
    value = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(value):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return value


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=64)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _public_user(user: User) -> dict[str, object]:
    name_parts = user.name.split(maxsplit=1)
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "google_connected": bool(user.google_subject),
        "google_email": user.email if user.google_subject else None,
        "password_login_enabled": user.password_login_enabled,
        "phone_number": user.phone_number,
        "first_name": name_parts[0] if name_parts else "",
        "last_name": name_parts[1] if len(name_parts) > 1 else "",
        "onboarding_completed": user.onboarding_completed,
        "onboarding_skipped": user.onboarding_skipped,
        "travel_preferences": TravelPreferences.model_validate(user.travel_preferences or {}).model_dump(),
    }


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    secure = _cookie_secure(request)
    samesite = os.getenv("AUTH_COOKIE_SAMESITE", "strict").strip().lower()
    if samesite not in {"strict", "lax", "none"}:
        raise RuntimeError("AUTH_COOKIE_SAMESITE must be strict, lax, or none")
    if samesite == "none":
        secure = True
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )


def _cookie_secure(request: Request) -> bool:
    secure_setting = os.getenv("AUTH_COOKIE_SECURE")
    return secure_setting.strip().lower() in {"1", "true", "yes"} if secure_setting is not None else request.url.hostname not in {"localhost", "127.0.0.1", "::1"}


def _frontend_base_url() -> str:
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def _clear_google_cookies(response: Response, request: Request) -> None:
    secure = _cookie_secure(request)
    for cookie in (GOOGLE_STATE_COOKIE, GOOGLE_NONCE_COOKIE, GOOGLE_VERIFIER_COOKIE):
        response.delete_cookie(cookie, path=GOOGLE_COOKIE_PATH, httponly=True, secure=secure, samesite="lax")


def _clear_google_link_cookies(response: Response, request: Request) -> None:
    secure = _cookie_secure(request)
    for cookie in (GOOGLE_LINK_STATE_COOKIE, GOOGLE_LINK_NONCE_COOKIE, GOOGLE_LINK_VERIFIER_COOKIE, GOOGLE_LINK_CHALLENGE_COOKIE):
        response.delete_cookie(cookie, path=GOOGLE_COOKIE_PATH, httponly=True, secure=secure, samesite="lax")


def _google_authorization_url(client_id: str, redirect_uri: str, state: str, nonce: str, verifier: str) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def _verify_google_identity(code: str, verifier: str, nonce: str, client_id: str, client_secret: str, redirect_uri: str) -> tuple[str, str, str]:
    token_response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=15,
    )
    token_response.raise_for_status()
    id_token_value = token_response.json().get("id_token")
    if not isinstance(id_token_value, str):
        raise ValueError("Google did not return an ID token")
    claims = google_id_token.verify_oauth2_token(id_token_value, GoogleRequest(), audience=client_id)
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("Google nonce did not match")
    if claims.get("email_verified") is not True:
        raise ValueError("Google account email is not verified")
    subject = str(claims.get("sub", ""))
    email = _normalize_email(str(claims.get("email", "")))
    name = str(claims.get("name", email.split("@", 1)[0])).strip()[:100]
    if not subject:
        raise ValueError("Google account has no subject")
    return subject, email, name


def _issue_session(user: User, db: Session, response: Response, request: Request) -> None:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user.id, token_hash=_token_digest(token), expires_at=datetime.now(timezone.utc) + SESSION_TTL))
    db.commit()
    _set_session_cookie(response, token, request)


def require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    allowed = {value.strip().rstrip("/") for value in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",") if value.strip()}
    if origin is None or origin.rstrip("/") not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Request origin is not allowed.")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 128:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_digest(token)))
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")
    user = db.get(User, session.user_id)
    if user is None:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return user


def require_trip_access(
    request: Request,
    trip_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_allowed_origin(request)
    if trip_id is None:
        return
    from app.models import Trip

    trip = db.get(Trip, trip_id)
    if trip is None or trip.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found.")


@router.post("/signup", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_allowed_origin)])
def signup(payload: SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = _normalize_email(payload.email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    user = User(
        name=payload.name.strip(),
        email=email,
        password_hash=_hash_password(payload.password),
        onboarding_completed=False,
        onboarding_skipped=False,
        travel_preferences={},
        role="user",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    db.refresh(user)
    _issue_session(user, db, response, request)
    return {"user": _public_user(user)}


@router.post("/login", dependencies=[Depends(require_allowed_origin)])
def login(payload: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    email = _normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.password_login_enabled or not _verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect.")
    _issue_session(user, db, response, request)
    return {"user": _public_user(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"user": _public_user(user)}


@router.post("/logout", dependencies=[Depends(require_allowed_origin)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token and len(token) <= 128:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_digest(token)))
        if session is not None:
            db.delete(session)
            db.commit()
    secure = _cookie_secure(request)
    samesite = os.getenv("AUTH_COOKIE_SAMESITE", "strict").strip().lower()
    response.delete_cookie(key=SESSION_COOKIE, path="/", httponly=True, secure=secure or samesite == "none", samesite=samesite)
    return {"ok": True}


def _smtp_is_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM_EMAIL"))


def _send_password_reset_email(email: str, token: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.environ["SMTP_FROM_EMAIL"]
    link = f"{_frontend_base_url()}/forgot-password#token={token}"
    message = EmailMessage()
    message["Subject"] = "Reset your GoWander password"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "We received a request to reset your GoWander password. "
        f"Use this one-time link within 30 minutes: {link}\n\n"
        "If you did not request this, you can ignore this message."
    )
    use_ssl = os.getenv("SMTP_USE_SSL", "false").strip().lower() in {"1", "true", "yes"}
    starttls = os.getenv("SMTP_STARTTLS", "true").strip().lower() in {"1", "true", "yes"}
    client_type = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    kwargs = {"context": ssl.create_default_context()} if use_ssl else {}
    with client_type(host, port, timeout=15, **kwargs) as smtp:
        if not use_ssl and starttls:
            smtp.starttls(context=ssl.create_default_context())
        username = os.getenv("SMTP_USERNAME")
        password = os.getenv("SMTP_PASSWORD")
        if username:
            smtp.login(username, password or "")
        smtp.send_message(message)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_allowed_origin)])
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    if not _smtp_is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Password reset email is not configured.")
    email = _normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
        recent_token = db.scalar(
            select(PasswordResetToken.id).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at >= recent_cutoff,
                PasswordResetToken.used_at.is_(None),
            )
        )
        if recent_token is not None:
            return {"message": "If an account exists for that address, a reset link will be sent."}
        db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        raw_token = secrets.token_urlsafe(32)
        reset = PasswordResetToken(
            user_id=user.id,
            token_hash=_token_digest(raw_token),
            expires_at=datetime.now(timezone.utc) + PASSWORD_RESET_TTL,
        )
        db.add(reset)
        db.commit()
        try:
            _send_password_reset_email(user.email, raw_token)
        except Exception:
            logger.exception("Password reset email delivery failed")
            db.delete(reset)
            db.commit()
    return {"message": "If an account exists for that address, a reset link will be sent."}


@router.post("/password-reset/confirm", dependencies=[Depends(require_allowed_origin)])
def confirm_password_reset(payload: PasswordResetComplete, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    token_hash = _token_digest(payload.token)
    reset = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    if reset is None or reset.used_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or expired.")
    expires_at = reset.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or expired.")
    consumed = db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.id == reset.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or expired.")
    user = db.get(User, reset.user_id)
    if user is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or expired.")
    user.password_hash = _hash_password(payload.password)
    user.password_login_enabled = True
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.id != reset.id))
    db.commit()
    return {"ok": True}


@router.get("/google/start")
def google_start(request: Request, response: Response):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not client_id or not os.getenv("GOOGLE_CLIENT_SECRET") or not redirect_uri:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google sign-in is not configured.")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    secure = _cookie_secure(request)
    redirect = RedirectResponse(_google_authorization_url(client_id, redirect_uri, state, nonce, verifier), status_code=status.HTTP_302_FOUND)
    for cookie, value in ((GOOGLE_STATE_COOKIE, state), (GOOGLE_NONCE_COOKIE, nonce), (GOOGLE_VERIFIER_COOKIE, verifier)):
        redirect.set_cookie(cookie, value, max_age=600, httponly=True, secure=secure, samesite="lax", path=GOOGLE_COOKIE_PATH)
    return redirect


@router.post("/google/link/start", dependencies=[Depends(require_allowed_origin)])
def google_link_start(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not client_id or not os.getenv("GOOGLE_CLIENT_SECRET") or not redirect_uri:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google sign-in is not configured.")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    session_token = request.cookies.get(SESSION_COOKIE, "")
    auth_session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_digest(session_token)))
    if auth_session is None or auth_session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    now = datetime.now(timezone.utc)
    db.execute(delete(OAuthLinkChallenge).where(OAuthLinkChallenge.auth_session_id == auth_session.id))
    db.execute(delete(OAuthLinkChallenge).where(OAuthLinkChallenge.expires_at <= now))
    challenge_token = secrets.token_urlsafe(32)
    db.add(OAuthLinkChallenge(
        user_id=user.id,
        auth_session_id=auth_session.id,
        token_hash=_token_digest(challenge_token),
        expires_at=now + timedelta(minutes=10),
    ))
    db.commit()
    authorization_url = _google_authorization_url(client_id, redirect_uri, state, nonce, verifier)
    secure = _cookie_secure(request)
    for cookie, value in (
        (GOOGLE_LINK_STATE_COOKIE, state),
        (GOOGLE_LINK_NONCE_COOKIE, nonce),
        (GOOGLE_LINK_VERIFIER_COOKIE, verifier),
        (GOOGLE_LINK_CHALLENGE_COOKIE, challenge_token),
    ):
        response.set_cookie(cookie, value, max_age=600, httponly=True, secure=secure, samesite="lax", path=GOOGLE_COOKIE_PATH)
    return {"authorization_url": authorization_url}


@router.delete("/google/link", dependencies=[Depends(require_allowed_origin)])
def google_link_disconnect(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.google_subject:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No Google account is connected.")
    if not user.password_login_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Set a password before disconnecting Google so you can still sign in.",
        )
    user.google_subject = None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Google account could not be disconnected.")
    return {"ok": True}


def _google_link_callback(
    request: Request,
    code: str | None,
    state: str | None,
    error: str | None,
    db: Session,
) -> RedirectResponse:
    state_cookie = request.cookies.get(GOOGLE_LINK_STATE_COOKIE, "")
    nonce_cookie = request.cookies.get(GOOGLE_LINK_NONCE_COOKIE, "")
    verifier_cookie = request.cookies.get(GOOGLE_LINK_VERIFIER_COOKIE, "")
    challenge_cookie = request.cookies.get(GOOGLE_LINK_CHALLENGE_COOKIE, "")

    def result(path: str) -> RedirectResponse:
        redirect = RedirectResponse(f"{_frontend_base_url()}{path}", status_code=status.HTTP_302_FOUND)
        _clear_google_link_cookies(redirect, request)
        return redirect

    if not state or not state_cookie or not nonce_cookie or not verifier_cookie or not challenge_cookie or not hmac.compare_digest(state, state_cookie):
        return result("/app/settings?tab=account&google_link=error")

    challenge = db.scalar(select(OAuthLinkChallenge).where(
        OAuthLinkChallenge.token_hash == _token_digest(challenge_cookie)
    ))
    if challenge is None:
        return result("/login?auth_error=google_link_session")
    challenge_expires_at = challenge.expires_at
    if challenge_expires_at.tzinfo is None:
        challenge_expires_at = challenge_expires_at.replace(tzinfo=timezone.utc)
    db.delete(challenge)
    db.commit()
    if challenge_expires_at <= datetime.now(timezone.utc):
        return result("/login?auth_error=google_link_session")
    auth_session = db.get(AuthSession, challenge.auth_session_id)
    expires_at = auth_session.expires_at if auth_session is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if auth_session is None or auth_session.user_id != challenge.user_id or expires_at <= datetime.now(timezone.utc):
        db.commit()
        return result("/login?auth_error=google_link_session")
    user = db.get(User, challenge.user_id)
    if user is None:
        db.commit()
        return result("/login?auth_error=google_link_session")

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if error or not code:
        return result("/app/settings?tab=account&google_link=error")
    if not client_id or not client_secret or not redirect_uri:
        return result("/app/settings?tab=account&google_link=error")

    try:
        subject, email, _name = _verify_google_identity(
            code, verifier_cookie, nonce_cookie, client_id, client_secret, redirect_uri
        )
    except Exception:
        logger.exception("Google account linking verification failed")
        return result("/app/settings?tab=account&google_link=error")

    if email != user.email:
        return result("/app/settings?tab=account&google_link=error")
    linked_user = db.scalar(select(User).where(User.google_subject == subject))
    if linked_user is not None and linked_user.id != user.id:
        return result("/app/settings?tab=account&google_link=error")
    if user.google_subject is not None and user.google_subject != subject:
        return result("/app/settings?tab=account&google_link=error")

    user.google_subject = subject
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return result("/app/settings?google_link=error")
    return result("/app/settings?tab=account&google_link=connected")


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if request.cookies.get(GOOGLE_LINK_STATE_COOKIE):
        return _google_link_callback(request, code, state, error, db)
    state_cookie = request.cookies.get(GOOGLE_STATE_COOKIE, "")
    nonce_cookie = request.cookies.get(GOOGLE_NONCE_COOKIE, "")
    verifier_cookie = request.cookies.get(GOOGLE_VERIFIER_COOKIE, "")
    if error or not code or not state or not state_cookie or not nonce_cookie or not verifier_cookie or not hmac.compare_digest(state, state_cookie):
        redirect = RedirectResponse(f"{_frontend_base_url()}/login?auth_error=google", status_code=status.HTTP_302_FOUND)
        _clear_google_cookies(redirect, request)
        return redirect

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google sign-in is not configured.")

    try:
        subject, email, name = _verify_google_identity(
            code, verifier_cookie, nonce_cookie, client_id, client_secret, redirect_uri
        )
    except Exception:
        logger.exception("Google sign-in verification failed")
        redirect = RedirectResponse(f"{_frontend_base_url()}/login?auth_error=google", status_code=status.HTTP_302_FOUND)
        _clear_google_cookies(redirect, request)
        return redirect

    user = db.scalar(select(User).where(User.google_subject == subject))
    if user is None:
        existing_email = db.scalar(select(User).where(User.email == email))
        if existing_email is not None:
            redirect = RedirectResponse(f"{_frontend_base_url()}/login?auth_error=google_account_exists", status_code=status.HTTP_302_FOUND)
            _clear_google_cookies(redirect, request)
            return redirect
        user = User(
            name=name or email,
            email=email,
            password_hash=_hash_password(secrets.token_urlsafe(48)),
            password_login_enabled=False,
            google_subject=subject,
            onboarding_completed=False,
            onboarding_skipped=False,
            travel_preferences={},
        )
        db.add(user)
    user.email = email
    if name:
        user.name = name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        redirect = RedirectResponse(f"{_frontend_base_url()}/login?auth_error=google", status_code=status.HTTP_302_FOUND)
        _clear_google_cookies(redirect, request)
        return redirect
    db.refresh(user)
    redirect = RedirectResponse(f"{_frontend_base_url()}/app/dashboard", status_code=status.HTTP_302_FOUND)
    _issue_session(user, db, redirect, request)
    _clear_google_cookies(redirect, request)
    return redirect
