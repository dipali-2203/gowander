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


def test_scenario_replanning_accepts_all_four_simulated_disruptions(client: TestClient):
    assert signup(client, "scenario-replan@example.com").status_code == 201
    created = client.post(
        "/api/v1/trips",
        headers={"Origin": ORIGIN},
        json={
            "destination": "Jaipur",
            "start_date": "2026-12-01",
            "end_date": "2026-12-01",
            "budget": 50000,
            "available_minutes_per_day": 1200,
            "start_latitude": 26.9124,
            "start_longitude": 75.7873,
            "preferences": {},
        },
    )
    assert created.status_code == 201
    trip_id = created.json()["id"]
    assert created.json()["origin_latitude"] is None
    assert created.json()["origin_longitude"] is None
    attractions = [
        {
            "id": "planned-museum",
            "name": "Planned Museum",
            "category": "museum",
            "latitude": 26.92,
            "longitude": 75.82,
            "cost": 100,
            "visit_minutes": 60,
            "preference_score": 0.9,
            "opening_minute": 540,
            "closing_minute": 1020,
        },
        {
            "id": "garden",
            "name": "Garden",
            "category": "park",
            "latitude": 26.93,
            "longitude": 75.83,
            "cost": 50,
            "visit_minutes": 60,
            "preference_score": 0.8,
            "opening_minute": 540,
            "closing_minute": 1020,
        },
    ]
    for kind in ("rainfall", "traffic", "crowding", "closure"):
        response = client.post(
            f"/api/v1/trips/{trip_id}/replan-scenario",
            headers={"Origin": ORIGIN},
            json={
                "attractions": attractions,
                "disruptions": [{
                    "kind": kind,
                    "severity": 0.6,
                    "affected_attraction_ids": ["planned-museum"] if kind == "closure" else [],
                }],
                "current_latitude": 26.9124,
                "current_longitude": 75.7873,
                "remaining_budget": 50000,
                "remaining_minutes": 1200,
                "completed_attraction_ids": [],
                "closed_attraction_ids": [],
                "previous_planned_attraction_ids": ["planned-museum", "garden"],
                "data_source": "synthetic",
            },
        )
        assert response.status_code == 200, f"{kind}: {response.text}"
        result = response.json()
        assert result["algorithm"] == "scenario_replan"
        assert result["data_source"] == "synthetic"
        assert len(result["disruptions_applied"]) == 1
        assert result["stops"] or result["warnings"]


def test_scenario_validation_errors_are_fastapi_detail_arrays(client: TestClient):
    assert signup(client, "scenario-validation@example.com").status_code == 201
    created = client.post(
        "/api/v1/trips",
        headers={"Origin": ORIGIN},
        json={
            "destination": "Jaipur",
            "start_date": "2026-12-01",
            "end_date": "2026-12-01",
            "budget": 50000,
            "available_minutes_per_day": 1200,
            "start_latitude": 26.9124,
            "start_longitude": 75.7873,
            "preferences": {},
        },
    )
    response = client.post(
        f"/api/v1/trips/{created.json()['id']}/replan-scenario",
        headers={"Origin": ORIGIN},
        json={
            "attractions": [{
                "id": "planned-museum", "name": "Planned Museum", "category": "museum",
                "latitude": 26.92, "longitude": 75.82, "visit_minutes": 60,
                "preference_score": 0.9,
            }],
            "disruptions": [{"kind": "rainfall", "severity": 2}],
            "current_latitude": 26.9124,
            "current_longitude": 75.7873,
            "remaining_budget": 50000,
            "remaining_minutes": 1200,
        },
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert any(error["loc"][-1] == "severity" for error in response.json()["detail"])


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
    complete_budget = previous_plan["budget_estimate"]["complete_budget"]
    assert complete_budget["schema_version"] == 2
    assert complete_budget["total_estimate"] is None
    assert {"intercity_outbound", "intercity_return"} <= set(complete_budget["unavailable_categories"])
    assert any("Intercity outbound cost is unavailable" in warning for warning in previous_plan["warnings"])
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
        json={
            "budget": 45000,
            "name": "Updated weekend",
            "origin_latitude": 28.6139,
            "origin_longitude": 77.2090,
            "planning_options": {"transportation_mode": "car", "intercity_transportation_mode": "bus"},
        },
    )
    assert updated.status_code == 200
    detail = client.get(f"/api/v1/trips/{trip_id}").json()
    assert detail["budget"] == 45000
    assert detail["name"] == "Updated weekend"
    assert detail["latest_itinerary"] == previous_plan
    assert detail["itinerary_stale"] is True
    assert detail["complete_budget_current"] is False
    assert detail["planning_inputs"]["attractions"][0]["id"] == "museum"
    assert detail["planning_options"]["traveler_count"] == 2
    assert detail["origin"] == "Delhi"
    assert detail["origin_latitude"] == pytest.approx(28.6139)
    assert detail["origin_longitude"] == pytest.approx(77.2090)
    assert detail["preferences"]["interests"] == {"heritage": 1.0, "spiritual": 1.0, "adventure": 1.0}
    assert detail["preferences"]["walking_tolerance"] == 0.8
    assert detail["planning_options"]["luxury_level"] == 3
    assert detail["planning_options"]["transportation_mode"] == "car"
    assert detail["planning_options"]["intercity_transportation_mode"] == "bus"
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


def test_weather_proposal_is_separate_until_accept_and_persists_revision(client: TestClient, monkeypatch):
    from app.database import get_db
    from app.models import Trip
    from app.services import weather_replanning

    assert signup(client, "weather-trip@example.com").status_code == 201
    created = client.post("/api/v1/trips", headers={"Origin": ORIGIN}, json={
        "destination": "Jaipur", "start_date": "2026-12-01", "end_date": "2026-12-02",
        "budget": 50000, "available_minutes_per_day": 1200,
        "start_latitude": 26.9, "start_longitude": 75.8,
    })
    trip_id = created.json()["id"]
    old_plan = {"trip_id": trip_id, "algorithm": "greedy_multiday", "data_source": "osm",
        "total_cost": 10, "total_travel_minutes": 15, "total_visit_minutes": 120,
        "satisfaction": .8, "risk_score": None, "risk_data_status": "unavailable", "feasible": True, "warnings": [],
        "days": [
            {"day_number": 1, "date": "2026-12-01", "stops": [{"attraction_id": "view", "name": "Viewpoint",
                "arrival_minute": 840, "departure_minute": 900, "travel_minutes_before": 10, "cost": 10,
                "preference_score": .8, "risk_score": None}], "total_cost": 10, "total_travel_minutes": 10,
                "total_visit_minutes": 60, "feasible": True, "warnings": []},
            {"day_number": 2, "date": "2026-12-02", "stops": [{"attraction_id": "other", "name": "Other",
                "arrival_minute": 600, "departure_minute": 660, "travel_minutes_before": 5, "cost": 0,
                "preference_score": .5, "risk_score": None}], "total_cost": 0, "total_travel_minutes": 5,
                "total_visit_minutes": 60, "feasible": True, "warnings": []},
        ]}
    catalog = [
        {"id": "view", "name": "Viewpoint", "category": "viewpoint", "latitude": 26.9, "longitude": 75.8,
         "cost": 10, "visit_minutes": 60, "preference_score": .8, "raw_tags": {}},
        {"id": "gallery", "name": "Indoor Gallery", "category": "museum", "latitude": 26.901, "longitude": 75.801,
         "cost": 5, "visit_minutes": 60, "preference_score": .7, "raw_tags": {"tourism": "museum"}},
        {"id": "other", "name": "Other", "category": "park", "latitude": 26.92, "longitude": 75.82,
         "cost": 0, "visit_minutes": 60, "preference_score": .5, "raw_tags": {}},
    ]
    db = next(app.dependency_overrides[get_db]())
    trip = db.get(Trip, trip_id)
    trip.latest_itinerary = old_plan
    trip.completed_attraction_ids = ["other"]
    trip.planning_inputs = {"attractions": catalog, "meal_breaks": [], "confirmed_activities": [], "data_source": "osm"}
    db.commit()
    db.close()

    def fake_fetch(points, **kwargs):
        data = {}
        for lat, lon in points:
            rain = 90 if (lat, lon) == (26.9, 75.8) else 0
            data[(lat, lon)] = {"provider": "open-meteo", "retrieved_at": "2026-11-30T00:00:00+00:00",
                "timezone": "Asia/Kolkata", "hourly": {"precipitation_probability": {"2026-12-01T14:00": rain},
                "precipitation": {"2026-12-01T14:00": 4 if rain else 0},
                "temperature_2m": {"2026-12-01T14:00": 27},
                "apparent_temperature": {"2026-12-01T14:00": 26},
                "wind_speed_10m": {"2026-12-01T14:00": 8},
                "weather_code": {"2026-12-01T14:00": 61 if rain else 0}}}
        return data
    monkeypatch.setattr(weather_replanning, "fetch_forecasts", fake_fetch)
    proposed = client.post(f"/api/v1/trips/{trip_id}/replan/weather", headers={"Origin": ORIGIN}, json={"day_number": 1})
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()
    assert proposal["revised_stops"][0]["attraction_id"] == "gallery"
    unchanged = client.get(f"/api/v1/trips/{trip_id}").json()["latest_itinerary"]
    assert unchanged["days"][0]["stops"][0]["attraction_id"] == "view"
    assert unchanged["days"][1]["stops"][0]["attraction_id"] == "other"
    assert client.get(f"/api/v1/trips/{trip_id}").json()["pending_itinerary_revision"]["proposal_id"] == proposal["proposal_id"]
    accepted = client.post(f"/api/v1/trips/{trip_id}/replan/weather/accept", headers={"Origin": ORIGIN},
        json={"proposal_id": proposal["proposal_id"], "base_revision": proposal["base_revision"]})
    assert accepted.status_code == 200, accepted.text
    saved = client.get(f"/api/v1/trips/{trip_id}").json()
    assert saved["itinerary_revision"] == 1
    assert saved["pending_itinerary_revision"] is None
    assert saved["latest_itinerary"]["days"][0]["stops"][0]["attraction_id"] == "gallery"
    assert "weather_assessment" in saved["latest_itinerary"]["days"][0]["stops"][0]
    assert saved["latest_itinerary"]["days"][1]["stops"][0]["attraction_id"] == "other"
    assert saved["latest_itinerary"]["days"][1]["stops"][0]["arrival_minute"] == 600
    assert saved["completed_attraction_ids"] == ["other"]
    assert saved["itinerary_history"][0]["itinerary"] == old_plan
    marked = client.put(f"/api/v1/trips/{trip_id}/completed-activities", headers={"Origin": ORIGIN},
        json={"completed_attraction_ids": ["gallery"], "itinerary_revision": 1})
    assert marked.status_code == 200
    assert client.get(f"/api/v1/trips/{trip_id}").json()["completed_attraction_ids"] == ["gallery"]
    next_proposal_response = client.post(
        f"/api/v1/trips/{trip_id}/replan/weather",
        headers={"Origin": ORIGIN},
        json={"day_number": 1},
    )
    assert next_proposal_response.status_code == 200, next_proposal_response.text
    next_proposal = next_proposal_response.json()
    rejected = client.post(f"/api/v1/trips/{trip_id}/replan/weather/reject", headers={"Origin": ORIGIN},
        json={"proposal_id": next_proposal["proposal_id"], "base_revision": next_proposal["base_revision"]})
    assert rejected.status_code == 200
    after_rejection = client.get(f"/api/v1/trips/{trip_id}").json()
    assert after_rejection["latest_itinerary"] == saved["latest_itinerary"]
    assert after_rejection["pending_itinerary_revision"] is None
    assert after_rejection["itinerary_revision"] == saved["itinerary_revision"]
    assert after_rejection["itinerary_history"] == saved["itinerary_history"]
    stale_proposal = client.post(f"/api/v1/trips/{trip_id}/replan/weather", headers={"Origin": ORIGIN}, json={"day_number": 1}).json()
    assert client.put(f"/api/v1/trips/{trip_id}", headers={"Origin": ORIGIN}, json={"budget": 49000}).status_code == 200
    stale_accept = client.post(f"/api/v1/trips/{trip_id}/replan/weather/accept", headers={"Origin": ORIGIN},
        json={"proposal_id": stale_proposal["proposal_id"], "base_revision": stale_proposal["base_revision"]})
    assert stale_accept.status_code == 404
    stale_view = client.get(f"/api/v1/trips/{trip_id}").json()
    # The current budget response is an in-memory addition; after the trip is
    # marked stale, its stored itinerary is returned without that current estimate.
    assert stale_view["latest_itinerary"]["days"] == saved["latest_itinerary"]["days"]
    assert stale_view["complete_budget_current"] is False
    assert stale_view["itinerary_history"] == saved["itinerary_history"]


def test_authenticated_pdf_export_uses_latest_persisted_one_and_multi_day_plans(client: TestClient):
    import re

    from app.database import get_db
    from app.models import Hotel, Trip, TripAccommodation
    from app.services.itinerary_pdf import _document_lines, _inr

    assert signup(client, "pdf-export@example.com").status_code == 201
    created = client.post("/api/v1/trips", headers={"Origin": ORIGIN}, json={
        "name": "Lake break", "origin": "Delhi", "destination": "Udaipur",
        "start_date": "2026-12-01", "end_date": "2026-12-02", "budget": 50000,
        "available_minutes_per_day": 1200, "start_latitude": 24.58, "start_longitude": 73.68,
        "planning_options": {"traveler_count": 3},
    })
    trip_id = created.json()["id"]
    db = next(app.dependency_overrides[get_db]())
    trip = db.get(Trip, trip_id)
    trip.planning_inputs = {"attractions": [
        {"id": "internal-stop-id", "name": "Revised Palace", "cost_known": True,
         "data_source": "osm", "attribution": "© OpenStreetMap contributors"},
    ]}
    trip.latest_itinerary = {
        "budget_estimate": {
            "total_estimated": 12500, "per_person": 4167, "daily_average": 6250,
            "budget_limit": 50000, "remaining_budget": 37500, "within_budget": True,
            "is_complete": True, "unknown_attraction_fee_count": 0, "last_updated": None,
            "categories": [{"label": "Accommodation", "amount": 8000, "assumptions": ["Standard stay"]}],
            "exclusions": ["Intercity travel is excluded."],
            "complete_budget": {
                "schema_version": 2, "currency": "INR",
                "categories": [{
                    "key": "intercity_outbound", "label": "Outbound intercity travel",
                    "amount": 1200, "currency": "INR", "status": "user_provided",
                    "source": "User input", "assumptions": ["Traveler estimate"],
                    "private_internal_id": "must-not-leak",
                }],
                "known_subtotal": 1200, "estimated_subtotal": 0, "partial_subtotal": 0,
                "unavailable_categories": [], "partial_categories": [],
                "completeness": "complete", "total_estimate": 1200,
                "budget_limit": 50000, "remaining_budget": 48800, "within_budget": True,
                "assumptions": ["Public assumption"], "exclusions": [],
                "private_metadata": "must-not-leak",
            },
        },
        "days": [{
            "day_number": 1, "date": "2026-12-01", "total_travel_minutes": 35,
            "reserved_break_minutes": 60, "meal_breaks": [{"start_minute": 780, "duration_minutes": 60}],
            "stops": [{
                "attraction_id": "internal-stop-id", "name": "Revised Palace",
                "arrival_minute": 600, "departure_minute": 690, "travel_minutes_before": 15,
                "cost": 300, "weather_assessment": {"provider": "open-meteo", "forecast_time": "2026-12-01T10:00",
                    "condition": "Heavy rain", "advisories": [{"type": "rain", "description": "Rain may affect outdoor visits."}]},
            }],
        }],
    }
    selected_hotel = Hotel(
        id="private-hotel-id", destination="Udaipur", name="Lake Side Stay", hotel_type="hotel",
        latitude=24.58, longitude=73.68, stars=None, amenities=[], nightly_price=None,
        price_currency=None, price_source=None, provider_name="openstreetmap",
        external_provider_id="node/private-hotel-id", source_dataset="Geofabrik test extract",
        license_name="ODbL-1.0", attribution="OpenStreetMap contributors", raw_tags={},
    )
    db.add(selected_hotel)
    db.flush()
    selection = TripAccommodation(trip_id=trip.id, hotel_id=selected_hotel.id)
    db.add(selection)
    db.flush()
    trip.accommodation_selection = selection
    document_text = " ".join(text for _, text in _document_lines(trip))
    assert "Revised Palace" in document_text
    assert "Lake Side Stay" in document_text
    assert "private-hotel-id" not in document_text
    assert "Nightly price unavailable" in document_text
    assert "Complete trip budget" in document_text
    assert "Outbound intercity travel" in document_text
    assert "User Provided" in document_text
    assert "Complete trip total" in document_text and "1,200" in document_text
    assert "must-not-leak" not in document_text
    assert "₹12,500" == _inr(12500)
    db.commit()
    db.close()

    one_day = client.get(f"/api/v1/trips/{trip_id}/export.pdf", headers={"Origin": ORIGIN})
    assert one_day.status_code == 200
    assert one_day.headers["content-type"].startswith("application/pdf")
    assert "attachment" in one_day.headers["content-disposition"]
    assert one_day.content.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s+/Page(?!s)\b", one_day.content)) >= 1

    db = next(app.dependency_overrides[get_db]())
    trip = db.get(Trip, trip_id)
    trip.end_date = date(2026, 12, 2)
    trip.latest_itinerary = {**trip.latest_itinerary, "days": [*trip.latest_itinerary["days"], {
        "day_number": 2, "date": "2026-12-02", "total_travel_minutes": 40,
        "reserved_break_minutes": 0, "meal_breaks": [],
        "stops": [
            {"attraction_id": f"private-id-{index}", "name": f"Lake activity {index}",
             "arrival_minute": 540 + index * 20, "departure_minute": 555 + index * 20,
             "travel_minutes_before": 8, "cost": 0}
            for index in range(35)
        ],
    }]}
    db.commit()
    db.close()
    multi_day = client.get(f"/api/v1/trips/{trip_id}/export.pdf", headers={"Origin": ORIGIN})
    assert multi_day.status_code == 200
    assert multi_day.content.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s+/Page(?!s)\b", multi_day.content)) >= 2


def test_share_links_are_private_to_owners_reusable_revocable_and_read_only(client: TestClient, monkeypatch):
    from app.database import get_db
    from app.models import Trip, TripShare

    monkeypatch.setenv("TRIP_SHARE_SECRET", "test-share-signing-key-that-is-at-least-32-chars")
    assert signup(client, "share-owner@example.com").status_code == 201
    created = client.post("/api/v1/trips", headers={"Origin": ORIGIN}, json={
        "name": "Private preferences stay private", "origin": "Delhi", "destination": "Udaipur",
        "start_date": "2026-12-01", "end_date": "2026-12-01", "budget": 50000,
        "available_minutes_per_day": 1200, "start_latitude": 24.58, "start_longitude": 73.68,
        "preferences": {"interests": {"private_interest": 1}},
        "planning_options": {"traveler_count": 2},
    })
    trip_id = created.json()["id"]
    db = next(app.dependency_overrides[get_db]())
    trip = db.get(Trip, trip_id)
    trip.latest_itinerary = {"budget_estimate": {
        "total_estimated": 1000, "per_person": 500, "daily_average": 1000,
        "budget_limit": 50000, "remaining_budget": 49000, "within_budget": True,
        "is_complete": True, "unknown_attraction_fee_count": 0, "last_updated": None,
        "daily_attraction_fees": [{
            "day_number": 1, "date": "2026-12-01", "scheduled_unique_attraction_count": 1,
            "fee_counted_attraction_count": 1, "verified_fee_total": 0,
            "estimated_fee_lower_total": 100, "estimated_fee_representative_total": 300,
            "estimated_fee_upper_total": 1000, "representative_total": 300,
            "lower_total": 100, "upper_total": 1000, "unresolved_attraction_count": 0,
            "currency": "INR", "status": "estimated", "assumptions": ["Estimate, not a quote."],
            "attractions": [{"attraction_id": "private-attraction-id", "status": "estimated"}],
        }],
        "categories": [], "exclusions": [],
        "complete_budget": {
            "schema_version": 2, "currency": "INR",
            "categories": [{"key": "food", "label": "Food", "amount": None,
                            "currency": "INR", "status": "unavailable", "source": None,
                            "assumptions": []}],
            "known_subtotal": 0, "estimated_subtotal": 0, "partial_subtotal": None,
            "unavailable_categories": ["food"], "partial_categories": [],
            "completeness": "incomplete", "total_estimate": None,
            "budget_limit": 50000, "remaining_budget": None, "within_budget": None,
            "assumptions": [], "exclusions": [],
        },
    }, "days": [{
        "day_number": 1, "date": "2026-12-01", "total_travel_minutes": 10,
        "meal_breaks": [], "stops": [{
            "attraction_id": "must-not-leak", "name": "City Palace", "arrival_minute": 600,
            "departure_minute": 660, "travel_minutes_before": 10, "cost": 0,
        }],
    }]}
    trip.planning_inputs = {"data_source": "osm", "attractions": [{
        "id": "must-not-leak", "name": "City Palace", "category": "history",
        "latitude": 24.5764, "longitude": 73.6835, "cost": 0,
        "cost_known": False, "data_source": "osm", "visit_minutes": 60,
        "preference_score": 0.8,
    }]}
    db.commit()
    db.close()

    first = client.post(f"/api/v1/trips/{trip_id}/share-link", headers={"Origin": ORIGIN})
    assert first.status_code == 200, first.text
    token = first.json()["token"]
    assert first.json()["reused"] is False
    second = client.post(f"/api/v1/trips/{trip_id}/share-link", headers={"Origin": ORIGIN})
    assert second.status_code == 200
    assert second.json() == {"token": token, "reused": True}

    db = next(app.dependency_overrides[get_db]())
    saved_share = db.query(TripShare).one()
    assert saved_share.public_id in token
    assert token != saved_share.public_id
    assert not hasattr(saved_share, "token")
    db.close()

    client.cookies.clear()
    public = client.get(f"/api/v1/shared/{token}")
    assert public.status_code == 200, public.text
    public_body = public.json()
    assert public_body["title"] == "Private preferences stay private"
    assert public_body["days"][0]["stops"][0]["name"] == "City Palace"
    public_budget = public_body["budget_estimate"]
    assert public_budget["complete_budget_current"] is True
    assert public_budget["complete_budget"]["total_estimate"] is None
    assert public_budget["complete_budget"]["categories"][0]["amount"] is None
    assert public_budget["complete_budget"]["categories"][0]["status"] == "unavailable"
    public_daily_fee = public_budget["daily_attraction_fees"][0]
    assert public_daily_fee["estimated_fee_representative_total"] == 300
    assert public_daily_fee["status"] == "estimated"
    assert "attractions" not in public_daily_fee
    assert "private-attraction-id" not in str(public_budget)
    assert "private_metadata" not in public_budget["complete_budget"]
    assert "private_internal_id" not in public_budget["complete_budget"]["categories"][0]
    assert "preferences" not in public_body
    assert "trip_id" not in public_body
    assert "traveler_email" not in public_body
    assert "attraction_id" not in public_body["days"][0]["stops"][0]
    assert client.post(f"/api/v1/shared/{token}").status_code == 405
    assert client.get(f"/api/v1/shared/{token}invalid").status_code == 404

    assert signup(client, "share-other@example.com").status_code == 201
    cross_owner = client.delete(f"/api/v1/trips/{trip_id}/share-link", headers={"Origin": ORIGIN})
    assert cross_owner.status_code == 404
    assert client.post(f"/api/v1/trips/{trip_id}/share-link", headers={"Origin": ORIGIN}).status_code == 404

    assert client.post("/api/v1/auth/login", headers={"Origin": ORIGIN}, json={
        "email": "share-owner@example.com", "password": "a-long-password-123",
    }).status_code == 200
    revoked = client.delete(f"/api/v1/trips/{trip_id}/share-link", headers={"Origin": ORIGIN})
    assert revoked.status_code == 200
    assert client.get(f"/api/v1/shared/{token}").status_code == 404
    again = client.post(f"/api/v1/trips/{trip_id}/share-link", headers={"Origin": ORIGIN})
    assert again.status_code == 200
    assert again.json()["token"] != token
    assert client.get(f"/api/v1/shared/{again.json()['token']}").status_code == 200


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


def test_hotel_recommendations_selection_budget_and_trip_ownership(client: TestClient, monkeypatch):
    from app.database import get_db
    from app.models import Hotel, Trip

    monkeypatch.setenv("TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_STANDARD", "1000")
    assert signup(client, "hotel-owner@example.com").status_code == 201
    created = client.post("/api/v1/trips", headers={"Origin": ORIGIN}, json={
        "name": "Hotel route test", "origin": "Delhi", "destination": "Jaipur",
        "start_date": "2026-12-01", "end_date": "2026-12-03", "budget": 40000,
        "available_minutes_per_day": 1200, "start_latitude": 26.9124, "start_longitude": 75.7873,
        "planning_options": {"traveler_count": 2, "accommodation_category": "standard", "luxury_level": 3},
    })
    trip_id = created.json()["id"]
    db = next(app.dependency_overrides[get_db]())
    trip = db.get(Trip, trip_id)
    trip.planning_inputs = {"data_source": "osm", "attractions": [
        {"id": "a", "name": "A", "category": "cultural", "latitude": 26.90, "longitude": 75.78,
         "cost": 0, "visit_minutes": 60, "preference_score": .5},
        {"id": "b", "name": "B", "category": "historical", "latitude": 26.93, "longitude": 75.80,
         "cost": 0, "visit_minutes": 60, "preference_score": .5},
    ]}
    trip.latest_itinerary = {"data_source": "osm", "days": [{
        "day_number": 1, "date": "2026-12-01", "total_cost": 0, "total_travel_minutes": 10,
        "stops": [{"attraction_id": "a", "name": "A", "arrival_minute": 540, "departure_minute": 600,
                   "travel_minutes_before": 10, "cost": 0},
                  {"attraction_id": "b", "name": "B", "arrival_minute": 660, "departure_minute": 720,
                   "travel_minutes_before": 10, "cost": 0}],
    }], "budget_estimate": {"total_estimated": 0, "categories": []}}
    db.add_all([
        Hotel(id="osm:node:near", destination="Jaipur", name="Central Stay", hotel_type="hotel",
              latitude=26.915, longitude=75.79, stars=4, amenities=["Breakfast"], address="Old City",
              nightly_price=2500, price_currency="INR", price_source="Explicit mapped room/night price",
              provider_name="openstreetmap", external_provider_id="node/near",
              source_url="https://www.openstreetmap.org/node/near", source_dataset="Northern Zone",
              license_name="ODbL-1.0", attribution="© OpenStreetMap contributors",
              raw_tags={"breakfast": "yes"}),
        Hotel(id="osm:node:remote", destination="Jaipur", name="Remote Stay", hotel_type="hostel",
              latitude=26.99, longitude=75.90, stars=None, amenities=[], provider_name="openstreetmap",
              external_provider_id="node/remote", raw_tags={}),
    ])
    db.commit()
    db.close()

    recommended = client.get(f"/api/v1/hotels/recommendations?trip_id={trip_id}")
    assert recommended.status_code == 200, recommended.text
    payload = recommended.json()
    assert payload["planned_attraction_count"] == 2
    assert payload["items"][0]["id"] == "osm:node:near"
    assert payload["items"][0]["distance_kind"] == "straight_line"
    assert payload["items"][0]["price_status"] == "sourced"
    assert payload["items"][0]["rating_status"] == "unavailable"
    assert payload["items"][0]["attribution"] == "© OpenStreetMap contributors"

    selected = client.put(
        f"/api/v1/trips/{trip_id}/accommodation", headers={"Origin": ORIGIN},
        json={"hotel_id": "osm:node:near"},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected_accommodation"]["name"] == "Central Stay"
    accommodation = next(
        item for item in selected.json()["latest_itinerary"]["budget_estimate"]["categories"]
        if item["key"] == "accommodation"
    )
    assert accommodation["amount"] == 5000
    assert accommodation["source"] == "selected_hotel"
    assert client.get(f"/api/v1/trips/{trip_id}").json()["selected_accommodation"]["name"] == "Central Stay"

    replacement = client.put(
        f"/api/v1/trips/{trip_id}/accommodation", headers={"Origin": ORIGIN},
        json={"hotel_id": "osm:node:remote"},
    )
    assert replacement.status_code == 200
    assert replacement.json()["selected_accommodation"]["name"] == "Remote Stay"
    fallback = next(
        item for item in replacement.json()["latest_itinerary"]["budget_estimate"]["categories"]
        if item["key"] == "accommodation"
    )
    assert fallback["amount"] == 2000
    removed = client.delete(f"/api/v1/trips/{trip_id}/accommodation", headers={"Origin": ORIGIN})
    assert removed.status_code == 200
    assert removed.json()["selected_accommodation"] is None
    assert next(item for item in removed.json()["latest_itinerary"]["budget_estimate"]["categories"]
                if item["key"] == "accommodation")["amount"] == 2000

    assert signup(client, "hotel-other@example.com").status_code == 201
    assert client.get(f"/api/v1/hotels/recommendations?trip_id={trip_id}").status_code == 404
    assert client.put(f"/api/v1/trips/{trip_id}/accommodation", headers={"Origin": ORIGIN},
                      json={"hotel_id": "osm:node:near"}).status_code == 404
