from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models import Attraction
from app.schemas import AttractionInput, Preferences
from app.services.planner import generate_greedy_itinerary
from app.services.poi_catalog import (
    DESTINATIONS,
    build_overpass_query,
    ingest_destination,
    normalize_category,
    normalize_osm_element,
    parse_overpass_response,
    to_optimizer_attraction,
)


def element(osm_id, *, osm_type="node", name="Amber Fort", lat=26.9855, lon=75.8513, tags=None):
    return {
        "type": osm_type, "id": osm_id,
        **({"lat": lat, "lon": lon} if osm_type == "node" else {"center": {"lat": lat, "lon": lon}}),
        "tags": {"name": name, **(tags or {})},
    }


def test_normalizes_osm_categories_and_keeps_unknown_planning_values_unknown():
    assert normalize_category({"historic": "castle"}) == "historical"
    assert normalize_category({"amenity": "museum"}) == "museum"
    assert normalize_category({"amenity": "place_of_worship"}) == "religious"
    assert normalize_category({"leisure": "garden"}) == "park"
    assert normalize_category({"tourism": "viewpoint"}) == "viewpoint"
    assert normalize_category({"amenity": "theatre"}) == "cultural"
    assert normalize_category({"shop": "gift"}) is None

    row = normalize_osm_element(element(1, tags={"tourism": "attraction"}), "jaipur")
    assert row is not None
    assert row["entrance_fee"] is None
    assert row["opening_hours"] is None
    assert row["visit_duration_minutes"] is None
    assert row["cost"] == 0  # optimizer compatibility projection, not a claimed free fee
    assert row["visit_minutes"] == 60  # optimizer fallback, surfaced as unverified
    assert row["provider_name"] == "openstreetmap"
    assert row["license_name"] == "ODbL-1.0"
    assert row["attribution"] == "© OpenStreetMap contributors"
    assert row["external_provider_id"] == "node/1"


def test_parser_rejects_bad_coordinates_and_collapses_nearby_duplicate_names():
    payload = {"elements": [
        element(1, tags={"tourism": "attraction"}),
        element(2, osm_type="way", name="Amber Fort", lat=26.9856, lon=75.8513, tags={"historic": "castle", "website": "https://example.org"}),
        element(3, name="Unnamed", lat=91, lon=75.8, tags={"tourism": "museum"}),
        element(4, name="Unmapped shop", tags={"shop": "gift"}),
        element(5, name="Outside city", lat=27.5, lon=75.8, tags={"tourism": "museum"}),
    ]}
    rows, duplicates, invalid = parse_overpass_response(payload, "jaipur")
    assert len(rows) == 1
    assert rows[0]["external_provider_id"] == "way/2"  # richer source record wins
    assert rows[0]["raw_tags"]["historic"] == "castle"
    assert duplicates == 1
    assert len(invalid) == 3
    query = build_overpass_query("jaipur")
    assert "26.75,75.68,27.05,76.0" in query
    with pytest.raises(ValueError):
        build_overpass_query("Delhi")


def test_ingestion_persists_records_and_refresh_preserves_curated_fields():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    class FakeResponse:
        status_code = 200
        headers = {}
        def raise_for_status(self): return None
        def json(self): return {"elements": [element(12, lat=24.5764, lon=73.6835,
            tags={"tourism": "museum", "opening_hours": "Mo-Su 09:00-17:00"})]}

    class FakeClient:
        def post(self, url, data):
            assert url.endswith("/api/interpreter")
            assert "24.45,73.6,24.72,73.85" in data["data"]
            return FakeResponse()

    try:
        with Session() as db:
            first = ingest_destination(db, "udaipur", client=FakeClient())
            saved = db.get(Attraction, "osm:node:12")
            saved.curated_entrance_fee = 150
            saved.curated_visit_duration_minutes = 90
            db.commit()
            second = ingest_destination(db, "udaipur", client=FakeClient())
            refreshed = db.get(Attraction, "osm:node:12")
            adapted = to_optimizer_attraction(refreshed)
            assert first["new_count"] == 1
            assert second["new_count"] == 0
            assert second["updated_count"] == 1
            assert refreshed.curated_entrance_fee == 150
            assert refreshed.curated_visit_duration_minutes == 90
            assert adapted["cost"] == 150
            assert adapted["cost_known"] is True
            assert adapted["opening_window_known"] is True
            assert adapted["category"] == "history"
            assert adapted["catalog_category"] == "museum"
            assert adapted["opening_minute"] == 540
            assert adapted["closing_minute"] == 1020
            assert adapted["data_freshness"] == "fresh"
            # The established optimizer schema still accepts the normalized row.
            optimizer_input = AttractionInput.model_validate(adapted)
            plan = generate_greedy_itinerary(
                attractions=[optimizer_input], preferences=Preferences(),
                start_latitude=24.5854, start_longitude=73.7125,
                budget=1000, available_minutes=1200,
            )
            assert plan["stops"][0].attraction_id == "osm:node:12"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def api_client(monkeypatch):
    monkeypatch.setenv("POI_ALLOW_SYNTHETIC_FALLBACK", "true")
    monkeypatch.setenv("POI_INGESTION_ENABLED", "true")
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:3000")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    def override_db():
        with TestingSession() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, TestingSession
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_catalog_endpoint_labels_synthetic_fallback_and_returns_db_provenance(api_client):
    client, TestingSession = api_client
    fallback = client.get("/api/v1/attractions/catalog/jaipur").json()
    assert fallback["catalog_status"] == "synthetic_fallback"
    assert fallback["data_source"] == "synthetic"
    assert "synthetic" in fallback["message"].lower()
    with TestingSession() as db:
        db.add(Attraction(
            id="osm:node:22", destination="Jaipur", name="Test Museum", category="museum",
            latitude=26.92, longitude=75.82, cost=0, visit_minutes=60,
            data_source="osm", provider_name="openstreetmap", external_provider_id="node/22",
            last_fetched_at=datetime.now(timezone.utc), data_freshness="fresh",
            verification_status="provider_retrieved", raw_tags={"tourism": "museum"},
            attribution="© OpenStreetMap contributors", license_name="ODbL-1.0",
        ))
        db.commit()
    catalog = client.get("/api/v1/attractions/catalog/jaipur").json()
    assert catalog["data_source"] == "osm"
    assert catalog["attribution"] == "© OpenStreetMap contributors"
    attraction = catalog["attractions"][0]
    assert attraction["cost_known"] is False
    assert attraction["opening_hours"] is None
    assert attraction["visit_duration_known"] is False
    assert attraction["provider_name"] == "openstreetmap"


def test_ingestion_endpoint_rejects_ordinary_authenticated_user(api_client):
    client, _ = api_client
    signup = client.post("/api/v1/auth/signup", headers={"Origin": "http://localhost:3000"}, json={
        "name": "Normal User", "email": "poi-user@example.com", "password": "a-long-password-123",
    })
    assert signup.status_code == 201
    assert client.post("/api/v1/attractions/admin/ingest/jaipur", headers={"Origin": "http://localhost:3000"}).status_code == 403

