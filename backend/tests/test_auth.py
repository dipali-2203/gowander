from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from urllib.parse import parse_qs, urlparse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuthSession, User


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("AUTH_COOKIE_SAMESITE", "strict")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


ORIGIN = "http://localhost:3000"


def signup(client: TestClient, email: str):
    return client.post(
        "/api/v1/auth/signup",
        headers={"Origin": ORIGIN},
        json={"name": "Test Traveler", "email": email, "password": "a-long-password-123"},
    )


def start_google_link(client: TestClient, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "example.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
    response = client.post("/api/v1/auth/google/link/start", headers={"Origin": ORIGIN})
    params = parse_qs(urlparse(response.json()["authorization_url"]).query)
    return response, params


def mock_google_exchange(monkeypatch, params, *, subject, email, nonce=None, expected_verifier=None):
    import httpx
    from app.api import auth

    def fake_post(url, data, timeout):
        if expected_verifier is not None and data["code_verifier"] != expected_verifier:
            request = httpx.Request("POST", url)
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("invalid_grant", request=request, response=response)

        class FakeTokenResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"id_token": "signed-test-token"}

        return FakeTokenResponse()

    monkeypatch.setattr(auth.httpx, "post", fake_post)
    monkeypatch.setattr(auth.google_id_token, "verify_oauth2_token", lambda *args, **kwargs: {
        "sub": subject,
        "email": email,
        "email_verified": True,
        "name": "Linked Traveler",
        "nonce": nonce if nonce is not None else params["nonce"][0],
    })


def test_signup_creates_scrypt_user_and_http_only_session(client: TestClient):
    response = signup(client, "one@example.com")
    assert response.status_code == 201
    assert response.json()["user"]["email"] == "one@example.com"
    assert response.cookies.get("gowander_session")
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=strict" in response.headers["set-cookie"].lower()

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["name"] == "Test Traveler"
    from app.database import get_db
    db = next(app.dependency_overrides[get_db]())
    stored = db.query(User).one()
    assert stored.password_hash.startswith("scrypt$")
    assert "a-long-password-123" not in stored.password_hash
    db.close()


def test_authenticated_trip_reliability_endpoint_returns_simulation(client: TestClient):
    assert signup(client, "risk@example.com").status_code == 201
    trip = client.post(
        "/api/v1/trips",
        headers={"Origin": ORIGIN},
        json={
            "destination": "Jaipur",
            "start_date": "2026-11-17",
            "end_date": "2026-11-17",
            "budget": 1000,
            "available_minutes_per_day": 480,
            "start_latitude": 26.9124,
            "start_longitude": 75.7873,
            "preferences": {},
        },
    )
    assert trip.status_code == 201

    response = client.post(
        f"/api/v1/trips/{trip.json()['id']}/risk-simulation",
        headers={"Origin": ORIGIN},
        json={
            "attractions": [{
                "id": "planned-stop",
                "name": "Planned stop",
                "category": "history",
                "latitude": 26.92,
                "longitude": 75.82,
                "cost": 100,
                "visit_minutes": 60,
                "preference_score": 0.8,
                "weather_risk": 0.1,
                "crowd_risk": 0.2,
                "availability_risk": 0.05,
            }],
            "scenarios": 1000,
            "seed": 42,
        },
    )

    assert response.status_code == 200
    assert response.json()["scenarios"] == 1000
    assert 0 <= response.json()["completion_probability"] <= 1
    assert response.json()["expected_disruptions"] >= 0


def test_trip_crud_persists_inputs_and_keeps_old_plan_when_edited(client: TestClient):
    assert signup(client, "trip-owner@example.com").status_code == 201
    created = client.post(
        "/api/v1/trips",
        headers={"Origin": ORIGIN},
        json={
            "name": "Weekend away",
            "origin": "Delhi",
            "destination": "Jaipur",
            "start_date": "2026-12-01",
            "end_date": "2026-12-01",
            "budget": 50000,
            "available_minutes_per_day": 1200,
            "start_latitude": 26.9124,
            "start_longitude": 75.7873,
            "preferences": {
                "interests": {"heritage": 1, "spiritual": 1, "adventure": 1},
                "risk_tolerance": 0.3,
                "walking_tolerance": 0.8,
                "crowd_tolerance": 0.5,
                "travel_pace": 0.5,
                "preferred_transport": "car",
            },
            "planning_options": {
                "traveler_count": 2,
                "transportation_mode": "train",
                "accommodation_category": "standard",
                "luxury_level": 3,
                "meal_preferences": ["vegetarian"],
                "miscellaneous_budget": 1000,
            },
        },
    )
    trip_id = created.json()["id"]
    plan = client.post(
        f"/api/v1/trips/{trip_id}/optimize-multiday",
        headers={"Origin": ORIGIN},
        json={
            "attractions": [{
                "id": "museum", "name": "Museum", "category": "history",
                "latitude": 26.92, "longitude": 75.82, "cost": 200,
                "visit_minutes": 60, "preference_score": 0.9,
                "opening_minute": 480, "closing_minute": 1080,
            }],
            "data_source": "synthetic",
            "meal_breaks": [{"start_minute": 780, "duration_minutes": 60}],
        },
    )
    assert plan.status_code == 200
    previous_plan = plan.json()
    assert previous_plan["budget_estimate"]["within_budget"] is True
    assert {item["key"] for item in previous_plan["budget_estimate"]["categories"]} == {
        "attractions", "transportation", "accommodation", "meals", "miscellaneous",
    }
    listed_trip = client.get("/api/v1/trips").json()[0]
    assert listed_trip["latest_itinerary"] == previous_plan
    attraction_payload = {
        "id": "museum", "name": "Museum", "category": "history",
        "latitude": 26.92, "longitude": 75.82, "cost": 200,
        "visit_minutes": 60, "preference_score": 0.9,
        "opening_minute": 480, "closing_minute": 1080,
    }
    assert client.post(
        f"/api/v1/trips/{trip_id}/pareto",
        headers={"Origin": ORIGIN},
        json={"attractions": [attraction_payload], "seed": 42, "max_alternatives": 2},
    ).status_code == 200
    assert client.post(
        f"/api/v1/trips/{trip_id}/anneal",
        headers={"Origin": ORIGIN},
        json={"attractions": [attraction_payload], "seed": 42},
    ).status_code == 200

    updated = client.put(
        f"/api/v1/trips/{trip_id}",
        headers={"Origin": ORIGIN},
        json={"budget": 45000, "name": "Updated weekend"},
    )
    assert updated.status_code == 200
    detail = client.get(f"/api/v1/trips/{trip_id}").json()
    assert detail["budget"] == 45000
    assert detail["name"] == "Updated weekend"
    assert detail["latest_itinerary"] == previous_plan
    assert detail["itinerary_stale"] is True
    assert detail["planning_inputs"]["attractions"][0]["id"] == "museum"
    assert detail["planning_options"]["traveler_count"] == 2
    assert detail["origin"] == "Delhi"
    assert detail["preferences"]["interests"] == {"heritage": 1.0, "spiritual": 1.0, "adventure": 1.0}
    assert detail["preferences"]["walking_tolerance"] == 0.8
    assert detail["planning_options"]["luxury_level"] == 3
    assert "pareto" in detail["optimization_results"]
    assert "simulated_annealing" in detail["optimization_results"]

    regenerated = client.post(f"/api/v1/trips/{trip_id}/regenerate", headers={"Origin": ORIGIN})
    assert regenerated.status_code == 200
    saved_replacement = regenerated.json()
    assert saved_replacement["trip_id"] == trip_id
    assert client.get(f"/api/v1/trips/{trip_id}").json()["itinerary_stale"] is False
    assert client.get(f"/api/v1/trips/{trip_id}").json()["optimization_results"] == {}
    assert client.put(f"/api/v1/trips/{trip_id}", headers={"Origin": ORIGIN}, json={"budget": 50}).status_code == 200
    rejected_replacement = client.post(f"/api/v1/trips/{trip_id}/regenerate", headers={"Origin": ORIGIN})
    assert rejected_replacement.status_code == 422
    assert client.get(f"/api/v1/trips/{trip_id}").json()["latest_itinerary"] == saved_replacement

    copied = client.post(f"/api/v1/trips/{trip_id}/duplicate", headers={"Origin": ORIGIN})
    assert copied.status_code == 201
    duplicate_id = copied.json()["id"]
    assert client.get(f"/api/v1/trips/{duplicate_id}").status_code == 200

    assert signup(client, "different-owner@example.com").status_code == 201
    assert client.get(f"/api/v1/trips/{trip_id}").status_code == 404
    assert client.put(f"/api/v1/trips/{trip_id}", headers={"Origin": ORIGIN}, json={"budget": 1}).status_code == 404
    assert client.delete(f"/api/v1/trips/{trip_id}", headers={"Origin": ORIGIN}).status_code == 404
    assert client.post(f"/api/v1/trips/{trip_id}/duplicate", headers={"Origin": ORIGIN}).status_code == 404
    assert client.get("/api/v1/trips").json() == []

    assert client.post("/api/v1/auth/login", headers={"Origin": ORIGIN}, json={
        "email": "trip-owner@example.com", "password": "a-long-password-123",
    }).status_code == 200
    assert client.delete(f"/api/v1/trips/{duplicate_id}", headers={"Origin": ORIGIN}).json() == {"ok": True}
    assert client.get(f"/api/v1/trips/{duplicate_id}").status_code == 404


def test_login_rejects_bad_password_and_logout_revokes_session(client: TestClient):
    assert signup(client, "two@example.com").status_code == 201
    bad = client.post("/api/v1/auth/login", headers={"Origin": ORIGIN}, json={"email": "two@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    good = client.post("/api/v1/auth/login", headers={"Origin": ORIGIN}, json={"email": "two@example.com", "password": "a-long-password-123"})
    assert good.status_code == 200
    assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_trip_endpoints_require_auth_and_enforce_owner(client: TestClient):
    unauthenticated = client.post("/api/v1/trips", json={})
    assert unauthenticated.status_code == 401

    assert signup(client, "owner@example.com").status_code == 201
    trip = client.post(
        "/api/v1/trips",
        headers={"Origin": ORIGIN},
        json={
            "destination": "Jaipur",
            "start_date": date.today().isoformat(),
            "end_date": (date.today() + timedelta(days=1)).isoformat(),
            "budget": 50000,
            "available_minutes_per_day": 480,
            "start_latitude": 26.9124,
            "start_longitude": 75.7873,
            "preferences": {},
        },
    )
    assert trip.status_code == 201
    trip_id = trip.json()["id"]
    assert client.get(f"/api/v1/trips/{trip_id}").status_code == 200

    client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    assert signup(client, "other@example.com").status_code == 201
    assert client.get(f"/api/v1/trips/{trip_id}").status_code == 404


def test_auth_mutations_reject_untrusted_origins(client: TestClient):
    response = client.post(
        "/api/v1/auth/signup",
        headers={"Origin": "https://attacker.example"},
        json={"name": "Bad Origin", "email": "bad@example.com", "password": "a-long-password-123"},
    )
    assert response.status_code == 403


def test_synthetic_catalog_remains_public(client: TestClient):
    response = client.get("/api/v1/attractions/catalog/jaipur")
    assert response.status_code == 200
    assert response.json()["data_source"] == "synthetic"


def test_password_reset_is_generic_single_use_and_revokes_sessions(client: TestClient, monkeypatch):
    assert signup(client, "reset@example.com").status_code == 201
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://localhost:3000")
    delivered = []
    from app.api import auth
    monkeypatch.setattr(auth, "_send_password_reset_email", lambda email, token: delivered.append((email, token)))

    known = client.post("/api/v1/auth/password-reset/request", headers={"Origin": ORIGIN}, json={"email": "reset@example.com"})
    unknown = client.post("/api/v1/auth/password-reset/request", headers={"Origin": ORIGIN}, json={"email": "missing@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(delivered) == 1
    token = delivered[0][1]

    completed = client.post("/api/v1/auth/password-reset/confirm", headers={"Origin": ORIGIN}, json={"token": token, "password": "a-new-password-456"})
    assert completed.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/password-reset/confirm", headers={"Origin": ORIGIN}, json={"token": token, "password": "another-password-789"}).status_code == 400
    assert client.post("/api/v1/auth/login", headers={"Origin": ORIGIN}, json={"email": "reset@example.com", "password": "a-long-password-123"}).status_code == 401
    assert client.post("/api/v1/auth/login", headers={"Origin": ORIGIN}, json={"email": "reset@example.com", "password": "a-new-password-456"}).status_code == 200


def test_google_start_uses_state_nonce_and_http_only_cookies(client: TestClient, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "example.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
    response = client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert response.status_code == 302
    location = urlparse(response.headers["location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["scope"] == ["openid email profile"]
    assert query["redirect_uri"] == ["http://localhost:8000/api/v1/auth/google/callback"]
    assert query["state"][0] == response.cookies["gowander_google_state"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43
    assert "httponly" in response.headers["set-cookie"].lower()


def test_google_callback_rejects_state_mismatch_without_creating_session(client: TestClient):
    response = client.get("/api/v1/auth/google/callback?code=fake&state=wrong", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/login?auth_error=google"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_google_callback_verifies_nonce_and_creates_local_session(client: TestClient, monkeypatch):
    import httpx
    from google.oauth2 import id_token

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "example.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    params = parse_qs(urlparse(start.headers["location"]).query)
    exchanged = {}

    class FakeTokenResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "signed-test-token"}

    def fake_post(url, data, timeout):
        exchanged.update(data)
        return FakeTokenResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda token, request, audience: {
        "sub": "google-subject-123", "email": "google@example.com", "email_verified": True,
        "name": "Google Traveler", "nonce": params["nonce"][0],
    })
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert callback.headers["location"] == "http://localhost:3000/app/dashboard"
    assert exchanged["redirect_uri"] == "http://localhost:8000/api/v1/auth/google/callback"
    assert exchanged["code_verifier"] == start.cookies["gowander_google_verifier"]
    assert client.get("/api/v1/auth/me").json()["user"]["email"] == "google@example.com"


def test_google_signin_does_not_auto_link_an_unverified_local_account(client: TestClient, monkeypatch):
    import httpx
    from google.oauth2 import id_token

    assert signup(client, "same@example.com").status_code == 201
    client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "example.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    params = parse_qs(urlparse(start.headers["location"]).query)

    class FakeTokenResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "signed-test-token"}

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeTokenResponse())
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *args, **kwargs: {
        "sub": "another-google-subject", "email": "same@example.com", "email_verified": True,
        "name": "Same Email", "nonce": params["nonce"][0],
    })
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.headers["location"] == "http://localhost:3000/login?auth_error=google_account_exists"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_google_signin_shows_explicit_link_instructions_for_existing_email(client: TestClient, monkeypatch):
    import httpx
    from app.api import auth

    assert signup(client, "same@example.com").status_code == 201
    client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "example.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    params = parse_qs(urlparse(start.headers["location"]).query)

    class FakeTokenResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "signed-test-token"}

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeTokenResponse())
    monkeypatch.setattr(auth.google_id_token, "verify_oauth2_token", lambda *args, **kwargs: {
        "sub": "unlinked-google-subject", "email": "same@example.com", "email_verified": True,
        "name": "Same Email", "nonce": params["nonce"][0],
    })
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.headers["location"] == "http://localhost:3000/login?auth_error=google_account_exists"


def test_google_link_requires_authentication(client: TestClient):
    response = client.post("/api/v1/auth/google/link/start", headers={"Origin": ORIGIN})
    assert response.status_code == 401


def test_google_link_success_preserves_password_login_and_can_sign_in_with_google(client: TestClient, monkeypatch):
    assert signup(client, "link@example.com").status_code == 201
    start, params = start_google_link(client, monkeypatch)
    expected_verifier = start.cookies["gowander_google_link_verifier"]
    mock_google_exchange(
        monkeypatch, params, subject="link-subject", email="link@example.com", expected_verifier=expected_verifier
    )

    # SameSite=Strict omits the session cookie on Google's cross-site callback.
    session_cookie = client.cookies.get("gowander_session")
    client.cookies.delete("gowander_session")
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.headers["location"] == "http://localhost:3000/app/settings?tab=account&google_link=connected"
    client.cookies.set("gowander_session", session_cookie, path="/")
    assert client.get("/api/v1/auth/me").json()["user"]["google_email"] == "link@example.com"

    assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 200
    client.cookies.clear()
    signed_in = client.get("/api/v1/auth/google/start", follow_redirects=False)
    login_params = parse_qs(urlparse(signed_in.headers["location"]).query)
    mock_google_exchange(monkeypatch, login_params, subject="link-subject", email="link@example.com")
    google_login = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={login_params['state'][0]}",
        follow_redirects=False,
    )
    assert google_login.headers["location"] == "http://localhost:3000/app/dashboard"
    assert client.get("/api/v1/auth/me").status_code == 200

    client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    password_login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "link@example.com", "password": "a-long-password-123"},
    )
    assert password_login.status_code == 200


def test_google_link_rejects_different_email_and_subject_owned_by_another_user(client: TestClient, monkeypatch):
    assert signup(client, "owner@example.com").status_code == 201
    start, params = start_google_link(client, monkeypatch)
    mock_google_exchange(monkeypatch, params, subject="other-subject", email="different@example.com")
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.headers["location"].endswith("/app/settings?tab=account&google_link=error")

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    db.add(User(
        name="Other", email="other@example.com", password_hash="unused",
        password_login_enabled=True, google_subject="owned-subject", role="user",
    ))
    db.commit()
    db.close()
    next(db_generator, None)

    start, params = start_google_link(client, monkeypatch)
    mock_google_exchange(monkeypatch, params, subject="owned-subject", email="owner@example.com")
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.headers["location"].endswith("/app/settings?tab=account&google_link=error")


def test_google_link_rejects_invalid_state_nonce_and_pkce(client: TestClient, monkeypatch):
    assert signup(client, "checks@example.com").status_code == 201
    start, params = start_google_link(client, monkeypatch)
    mock_google_exchange(monkeypatch, params, subject="state-subject", email="checks@example.com")
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state=wrong",
        follow_redirects=False,
    )
    assert callback.headers["location"].endswith("/app/settings?tab=account&google_link=error")

    start, params = start_google_link(client, monkeypatch)
    mock_google_exchange(monkeypatch, params, subject="nonce-subject", email="checks@example.com", nonce="wrong")
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.headers["location"].endswith("/app/settings?tab=account&google_link=error")

    start, params = start_google_link(client, monkeypatch)
    expected_verifier = start.cookies["gowander_google_link_verifier"]
    mock_google_exchange(
        monkeypatch, params, subject="pkce-subject", email="checks@example.com", expected_verifier=expected_verifier
    )
    client.cookies.set("gowander_google_link_verifier", "invalid-verifier", path="/api/v1/auth/google")
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.headers["location"].endswith("/app/settings?tab=account&google_link=error")


def test_google_link_rechecks_expired_session_and_disconnect_prevents_lockout(client: TestClient, monkeypatch):
    assert signup(client, "expired-link@example.com").status_code == 201
    start, params = start_google_link(client, monkeypatch)
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    session = db.query(AuthSession).one()
    session.expires_at = session.expires_at.replace(year=2000)
    db.commit()
    db.close()
    next(db_generator, None)
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.headers["location"] == "http://localhost:3000/login?auth_error=google_link_session"

    # A Google-only account cannot remove its sole sign-in method.
    client.cookies.clear()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "example.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
    start_login = client.get("/api/v1/auth/google/start", follow_redirects=False)
    login_params = parse_qs(urlparse(start_login.headers["location"]).query)
    mock_google_exchange(monkeypatch, login_params, subject="google-only-subject", email="google-only@example.com")
    google_login = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={login_params['state'][0]}",
        follow_redirects=False,
    )
    assert google_login.status_code == 302
    disconnected = client.delete("/api/v1/auth/google/link", headers={"Origin": ORIGIN})
    assert disconnected.status_code == 409
    assert "Set a password" in disconnected.json()["detail"]


def test_password_user_can_disconnect_google_account(client: TestClient, monkeypatch):
    assert signup(client, "disconnect@example.com").status_code == 201
    start, params = start_google_link(client, monkeypatch)
    mock_google_exchange(monkeypatch, params, subject="disconnect-subject", email="disconnect@example.com")
    callback = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={params['state'][0]}",
        follow_redirects=False,
    )
    assert callback.headers["location"].endswith("tab=account&google_link=connected")
    response = client.delete("/api/v1/auth/google/link", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me").json()["user"]["google_connected"] is False
