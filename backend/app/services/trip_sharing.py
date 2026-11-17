"""Signed, revocable bearer links for read-only trip sharing."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from fastapi import HTTPException


def _secret() -> bytes:
    value = os.getenv("TRIP_SHARE_SECRET", "").strip()
    if len(value) < 32:
        raise HTTPException(
            status_code=503,
            detail="Trip sharing is not configured. Set TRIP_SHARE_SECRET to a random value of at least 32 characters.",
        )
    return value.encode("utf-8")


def new_public_id() -> str:
    return secrets.token_urlsafe(32)


def build_share_token(public_id: str, trip_id: int) -> str:
    message = f"gowander-trip-share:{trip_id}:{public_id}".encode("utf-8")
    signature = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return f"{public_id}.{signature}"


def verify_share_token(token: str, trip_id: int, public_id: str) -> bool:
    supplied_id, separator, supplied_signature = token.partition(".")
    if not separator or supplied_id != public_id or len(supplied_signature) != 64:
        return False
    expected = build_share_token(public_id, trip_id).partition(".")[2]
    return hmac.compare_digest(supplied_signature, expected)
