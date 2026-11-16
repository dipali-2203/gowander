from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Trip


ORIGIN = "http://localhost:3000"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGINS", ORIGIN)
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
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


def signup(client: TestClient, email: str, name: str = "Test Traveler"):
    return client.post(
        "/api/v1/auth/signup",
        headers={"Origin": ORIGIN},
        json={"name": name, "email": email, "password": "a-long-password-123"},
    )


def logout(client: TestClient):
    return client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})


def test_profile_update_persists_and_rejects_email_changes(client: TestClient):
    assert signup(client, "profile@example.com", "Original Name").status_code == 201
    profile = client.get("/api/v1/account/profile")
    assert profile.status_code == 200
    assert profile.json()["profile"]["first_name"] == "Original"
    assert profile.json()["profile"]["last_name"] == "Name"
    assert profile.json()["profile"]["email"] == "profile@example.com"

    updated = client.patch(
        "/api/v1/account/profile",
        headers={"Origin": ORIGIN},
        json={"first_name": "New", "last_name": "Traveler", "phone_number": "+91 98765 43210"},
    )
    assert updated.status_code == 200
    assert updated.json()["profile"]["name"] == "New Traveler"
    assert updated.json()["profile"]["phone_number"] == "+91 98765 43210"
    assert client.get("/api/v1/auth/me").json()["user"]["name"] == "New Traveler"
    assert client.patch(
        "/api/v1/account/profile",
        headers={"Origin": ORIGIN},
        json={"first_name": "New", "last_name": "Name", "email": "other@example.com"},
    ).status_code == 422


def test_profile_preferences_and_bookmarks_are_isolated_between_users(client: TestClient):
    assert signup(client, "user-a@example.com", "User A").status_code == 201
    initial = client.get("/api/v1/account/preferences").json()
    assert initial["preferences"]["interests"] == []
    assert initial["onboarding_completed"] is False
    selected = {
        "interests": ["Mountains and Trekking", "Photography"],
        "styles": ["Slow Travel"],
        "budget_preference": "moderate",
        "daily_budget_inr": 5000,
        "transportation": "Train",
        "accommodation": None,
        "preferred_trip_duration_days": 5,
        "travel_pace": "relaxed",
    }
    assert client.put("/api/v1/account/preferences", headers={"Origin": ORIGIN}, json=selected).status_code == 200
    assert client.post("/api/v1/account/bookmarks/manali", headers={"Origin": ORIGIN}).status_code == 201
    assert client.post("/api/v1/account/bookmarks/leh", headers={"Origin": ORIGIN}).status_code == 201
    assert client.post("/api/v1/account/bookmarks/manali", headers={"Origin": ORIGIN}).status_code == 409
    assert client.get("/api/v1/account/bookmarks").json()["items"] == [
        {"destination_id": "manali"}, {"destination_id": "leh"}
    ]

    logout(client)
    assert signup(client, "user-b@example.com", "User B").status_code == 201
    assert client.get("/api/v1/account/profile").json()["profile"]["name"] == "User B"
    assert client.get("/api/v1/account/preferences").json()["preferences"]["interests"] == []
    assert client.get("/api/v1/account/bookmarks").json()["items"] == []

    assert client.post(
        "/api/v1/account/onboarding/complete",
        headers={"Origin": ORIGIN},
        json={**selected, "interests": ["Beaches", "Food and Culinary Experiences"]},
    ).status_code == 200
    assert client.get("/api/v1/account/preferences").json()["preferences"]["interests"] == [
        "Beaches", "Food and Culinary Experiences"
    ]


def test_onboarding_skip_can_be_completed_later_and_survives_login(client: TestClient):
    assert signup(client, "onboarding@example.com").status_code == 201
    skipped = client.post(
        "/api/v1/account/onboarding/skip",
        headers={"Origin": ORIGIN},
        json={"interests": ["Heritage and History"]},
    )
    assert skipped.status_code == 200
    assert skipped.json()["onboarding_completed"] is False
    assert client.get("/api/v1/auth/me").json()["user"]["onboarding_skipped"] is True
    logout(client)
    assert client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "onboarding@example.com", "password": "a-long-password-123"},
    ).status_code == 200
    assert client.get("/api/v1/account/preferences").json()["onboarding_skipped"] is True
    complete = client.post(
        "/api/v1/account/onboarding/complete",
        headers={"Origin": ORIGIN},
        json={"interests": ["Beaches"], "styles": [], "budget_preference": None},
    )
    assert complete.status_code == 200
    assert complete.json()["user"]["onboarding_completed"] is True
    assert complete.json()["user"]["onboarding_skipped"] is False


def test_user_trip_list_only_returns_authenticated_users_trips(client: TestClient):
    assert signup(client, "trip-a@example.com").status_code == 201
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    from app.models import User
    owner = db.query(User).filter_by(email="trip-a@example.com").one()
    db.add(Trip(
        owner_user_id=owner.id,
        destination="Manali",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=2),
        budget=12000,
        available_minutes_per_day=480,
        start_latitude=32.2432,
        start_longitude=77.1892,
        preferences={},
    ))
    db.commit()
    db.close()
    next(db_generator, None)
    assert [trip["destination"] for trip in client.get("/api/v1/trips").json()] == ["Manali"]

    logout(client)
    assert signup(client, "trip-b@example.com").status_code == 201
    assert client.get("/api/v1/trips").json() == []


def test_bookmarks_cannot_be_read_or_changed_without_authentication(client: TestClient):
    assert client.get("/api/v1/account/bookmarks").status_code == 401
    assert client.post("/api/v1/account/bookmarks/goa", headers={"Origin": ORIGIN}).status_code == 401
    assert client.delete("/api/v1/account/bookmarks/goa", headers={"Origin": ORIGIN}).status_code == 401


def test_profile_migration_preserves_existing_users_and_marks_them_onboarded(monkeypatch):
    from app import database

    migration_engine = create_engine("sqlite://")
    with migration_engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(100), email VARCHAR(320), password_hash VARCHAR(256))"
        ))
        connection.execute(text(
            "INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Existing User', 'existing@example.com', 'stored-hash')"
        ))
    monkeypatch.setattr(database, "engine", migration_engine)

    database.migrate_user_profile_schema()
    database.migrate_user_profile_schema()

    columns = {column["name"] for column in inspect(migration_engine).get_columns("users")}
    assert {"phone_number", "onboarding_completed", "onboarding_skipped", "travel_preferences"} <= columns
    with migration_engine.connect() as connection:
        row = connection.execute(text(
            "SELECT name, email, password_hash, onboarding_completed, onboarding_skipped, travel_preferences FROM users WHERE id = 1"
        )).one()
    assert row == ("Existing User", "existing@example.com", "stored-hash", 1, 0, "{}")
    migration_engine.dispose()
