"""Bounded OpenStreetMap attraction ingestion and optimizer adapter."""
from __future__ import annotations

import re
import time
import os
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attraction, AttractionIngestionJob
from app.services.attraction_priority import attraction_priority


OVERPASS_URL = "https://overpass.private.coffee/api/interpreter"
OVERPASS_TIMEOUT_SECONDS = 25
OVERPASS_MAX_ATTEMPTS = 2
OVERPASS_RETRY_MAX_SECONDS = 8.0
MAX_RESULTS = 1200
FRESHNESS_TTL = timedelta(days=30)
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
OSM_LICENSE = "ODbL-1.0"

# Queries are deliberately bounded to city areas and a fixed set of tourism tags.
DESTINATIONS: dict[str, dict[str, Any]] = {
    "jaipur": {"name": "Jaipur", "bbox": (26.75, 75.68, 27.05, 76.00), "start": (26.9124, 75.7873)},
    "udaipur": {"name": "Udaipur", "bbox": (24.45, 73.60, 24.72, 73.85), "start": (24.5854, 73.7125)},
}


def normalize_category(tags: dict[str, str]) -> str | None:
    tourism = tags.get("tourism", "").lower()
    historic = tags.get("historic", "").lower()
    amenity = tags.get("amenity", "").lower()
    leisure = tags.get("leisure", "").lower()
    natural = tags.get("natural", "").lower()
    if tourism in {"museum"} or amenity == "museum":
        return "museum"
    if amenity == "place_of_worship" or tags.get("building", "").lower() == "temple":
        return "religious"
    if leisure in {"park", "garden", "nature_reserve"}:
        return "park"
    if natural in {"water", "lake"} or tourism in {"viewpoint"}:
        return "viewpoint"
    if amenity in {"theatre", "arts_centre", "cinema", "arts_center"} or tourism in {"artwork", "gallery"}:
        return "cultural"
    if tourism in {"theme_park", "zoo", "aquarium", "attraction"}:
        return "entertainment" if tourism in {"theme_park", "zoo", "aquarium"} else "other"
    if historic or tags.get("heritage"):
        return "historical"
    if tourism:
        return "other"
    return None


def build_overpass_query(destination: str) -> str:
    config = DESTINATIONS.get(destination.strip().lower())
    if config is None:
        raise ValueError("Only Jaipur and Udaipur ingestion is enabled.")
    south, west, north, east = config["bbox"]
    bbox = f"{south},{west},{north},{east}"
    return f"""[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}][maxsize:33554432];
(nwr[\"tourism\"~\"^(attraction|museum|artwork|gallery|viewpoint|zoo|aquarium|theme_park)$\"][\"name\"]({bbox});
 nwr[\"historic\"~\"^(castle|monument|memorial|ruins|archaeological_site|fort|palace|city_gate|wayside_shrine|wayside_cross)$\"][\"name\"]({bbox});
 nwr[\"amenity\"~\"^(museum|place_of_worship|theatre|arts_centre|cinema)$\"][\"name\"]({bbox});
 nwr[\"leisure\"~\"^(park|garden|nature_reserve)$\"][\"name\"]({bbox});
 nwr[\"natural\"~\"^(water|lake)$\"][\"name\"]({bbox}););
out center tags;"""


def _coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    point = element if "lat" in element and "lon" in element else element.get("center")
    if not isinstance(point, dict):
        return None
    try:
        lat, lon = float(point["lat"]), float(point["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(radians, a)
    lat2, lon2 = map(radians, b)
    value = sin((lat2-lat1)/2) ** 2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2) ** 2
    return 6371 * 2 * asin(sqrt(min(1.0, max(0.0, value))))


def _normalized_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", decomposed).strip()


def normalize_osm_element(element: dict[str, Any], destination: str, *, fetched_at: datetime | None = None) -> dict[str, Any] | None:
    tags = element.get("tags")
    if not isinstance(tags, dict):
        return None
    name = str(tags.get("name:en") or tags.get("name") or "").strip()
    category = normalize_category(tags)
    location = _coordinates(element)
    try:
        osm_id = int(element["id"])
        osm_type = str(element["type"]).lower()
    except (KeyError, TypeError, ValueError):
        return None
    if not name or not category or location is None or osm_type not in {"node", "way", "relation"}:
        return None
    if destination not in DESTINATIONS:
        return None
    south, west, north, east = DESTINATIONS[destination]["bbox"]
    lat, lon = location
    if not (south <= lat <= north and west <= lon <= east):
        return None
    osm_key = f"{osm_type}/{osm_id}"
    raw_tags = {str(key): str(value)[:500] for key, value in tags.items() if isinstance(value, (str, int, float, bool))}
    fetched = fetched_at or datetime.now(timezone.utc)
    return {
        "id": f"osm:{osm_type}:{osm_id}", "destination": DESTINATIONS[destination]["name"],
        "name": name[:150], "category": category, "latitude": lat, "longitude": lon,
        "cost": 0.0, "visit_minutes": 60, "preference_score": 0.5,
        "weather_risk": 0.0, "crowd_risk": 0.0, "availability_risk": 0.0,
        "weather_risk_known": False, "crowd_risk_known": False, "availability_risk_known": False,
        "risk_metadata": {},
        "opening_minute": 0, "closing_minute": 1440, "fatigue_score": 0.5,
        "data_source": "osm", "provider_name": "openstreetmap", "external_provider_id": osm_key,
        "source_url": f"https://www.openstreetmap.org/{osm_key}", "license_name": OSM_LICENSE,
        "attribution": OSM_ATTRIBUTION, "last_fetched_at": fetched, "data_freshness": "fresh",
        "verification_status": "provider_retrieved", "data_confidence": 0.4,
        "raw_tags": raw_tags, "opening_hours": str(tags.get("opening_hours") or "")[:500] or None,
        # Fee/hours/duration stay unknown unless OSM supplies an unambiguous value.
        "entrance_fee": None, "entrance_fee_currency": None, "visit_duration_minutes": None,
        "curated_opening_hours": None, "curated_entrance_fee": None,
        "curated_visit_duration_minutes": None,
    }


def _parse_simple_hours(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.fullmatch(r"(?:(?:Mo-Su)\s+)?(\d{2}):(\d{2})-(\d{2}):(\d{2})", value.strip())
    if not match:
        return None
    sh, sm, eh, em = map(int, match.groups())
    if sh > 23 or eh > 24 or sm > 59 or em > 59 or (eh == 24 and em != 0):
        return None
    opening, closing = sh * 60 + sm, eh * 60 + em
    return (opening, closing) if closing > opening else None


def parse_overpass_response(
    payload: dict[str, Any], destination: str, *, max_results: int | None = MAX_RESULTS
) -> tuple[list[dict[str, Any]], int, list[str]]:
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("Overpass response did not include an elements array.")
    if max_results is not None and len(elements) > max_results:
        raise ValueError(f"Overpass result exceeded the {max_results}-element ingestion safety limit.")
    normalized: list[dict[str, Any]] = []
    duplicate_count = 0
    invalid: list[str] = []
    # Duplicate geometries with nearly identical names are collapsed; retain the richer tag record.
    for element in elements:
        row = normalize_osm_element(element, destination)
        if row is None:
            invalid.append(str(element.get("id", "unknown")))
            continue
        current_key = _normalized_name(row["name"])
        duplicate_index = next((idx for idx, old in enumerate(normalized)
            if current_key == _normalized_name(old["name"])
            and _distance_km((row["latitude"], row["longitude"]), (old["latitude"], old["longitude"])) <= 0.075), None)
        if duplicate_index is None:
            normalized.append(row)
            continue
        duplicate_count += 1
        old = normalized[duplicate_index]
        if len(row["raw_tags"]) > len(old["raw_tags"]):
            normalized[duplicate_index] = row
    return normalized, duplicate_count, invalid


def persist_normalized_rows(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    destination: str,
    source_dataset: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Upsert normalized provider records by stable OSM identity."""
    discovered: list[str] = []
    updated: list[str] = []
    for source_row in rows:
        row = dict(source_row)
        row["source_dataset"] = source_dataset
        existing_id = db.scalar(select(Attraction.id).where(
            Attraction.provider_name == row["provider_name"],
            Attraction.external_provider_id == row["external_provider_id"],
        ))
        if existing_id is None:
            existing_id = db.scalar(select(Attraction.id).where(Attraction.id == row["id"]))
        if existing_id is None:
            discovered.append(row["id"])
            if not dry_run:
                db.add(Attraction(**row))
            continue
        updated.append(existing_id)
        if not dry_run:
            existing = db.get(Attraction, existing_id)
            if existing is None:
                raise RuntimeError(f"Attraction disappeared during import: {existing_id}")
            for field in (
                "name", "category", "latitude", "longitude", "raw_tags", "opening_hours",
                "source_url", "attribution", "license_name", "last_fetched_at", "data_freshness",
                "data_confidence", "source_dataset",
            ):
                setattr(existing, field, row[field])
            for field in ("provider_name", "external_provider_id", "data_source"):
                if not getattr(existing, field):
                    setattr(existing, field, row[field])
    if not dry_run:
        db.commit()
    return {
        "newly_discovered": discovered, "new_count": len(discovered),
        "updated_count": len(updated), "updated_ids": updated,
    }


def _call_overpass(client: httpx.Client, destination: str) -> dict[str, Any]:
    last_error: Exception | None = None
    endpoint = os.getenv("OSM_OVERPASS_URL", OVERPASS_URL)
    query = build_overpass_query(destination)
    for attempt in range(OVERPASS_MAX_ATTEMPTS):
        try:
            response = client.post(endpoint, data={"data": query})
            if response.status_code == 429 or response.status_code in {502, 503, 504}:
                last_error = httpx.HTTPStatusError(
                    f"Overpass returned HTTP {response.status_code}.", request=response.request, response=response
                )
                if attempt + 1 < OVERPASS_MAX_ATTEMPTS:
                    retry_after = response.headers.get("Retry-After", "").strip()
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        try:
                            retry_date = parsedate_to_datetime(retry_after)
                            if retry_date.tzinfo is None:
                                retry_date = retry_date.replace(tzinfo=timezone.utc)
                            delay = max(0.0, (retry_date - datetime.now(timezone.utc)).total_seconds())
                        except (TypeError, ValueError, OverflowError):
                            delay = 1.0 * (2 ** attempt)
                    if delay > OVERPASS_RETRY_MAX_SECONDS:
                        break  # Do not retry earlier than the provider requested.
                    time.sleep(max(0.0, delay))
                    continue
                break
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Overpass returned a non-object response.")
            return payload
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
            if attempt + 1 < OVERPASS_MAX_ATTEMPTS:
                time.sleep(min(OVERPASS_RETRY_MAX_SECONDS, 1.0 * (2 ** attempt)))
        except (httpx.HTTPError, ValueError):
            raise
    if isinstance(last_error, httpx.ReadTimeout):
        reason = "read timeout while waiting for Overpass response"
    elif isinstance(last_error, httpx.ConnectTimeout):
        reason = "connection timeout while connecting to Overpass"
    elif isinstance(last_error, httpx.ConnectError):
        reason = "connection failure to Overpass (check DNS/network/TLS)"
    elif isinstance(last_error, httpx.HTTPStatusError):
        reason = f"Overpass returned HTTP {last_error.response.status_code}"
    elif last_error is not None:
        reason = f"{type(last_error).__name__}: {last_error}"
    else:
        reason = "unknown Overpass request failure"
    raise RuntimeError(
        f"OpenStreetMap ingestion failed after {OVERPASS_MAX_ATTEMPTS} bounded attempts: {reason}."
    ) from last_error


def ingest_destination(db: Session, destination: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    key = destination.strip().lower()
    if key not in DESTINATIONS:
        raise ValueError("Only Jaipur and Udaipur ingestion is enabled.")
    owned_client = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(OVERPASS_TIMEOUT_SECONDS),
        headers={"User-Agent": os.getenv("OSM_USER_AGENT", "GoWander-POI-Ingestion/1.0 (local catalog refresh)")},
    )
    try:
        payload = _call_overpass(http, key)
    finally:
        if owned_client:
            http.close()
    rows, duplicates, invalid = parse_overpass_response(payload, key)
    now = datetime.now(timezone.utc)
    persisted = persist_normalized_rows(db, rows, destination=key, source_dataset="Overpass API")
    return {
        "destination": DESTINATIONS[key]["name"], "provider": "openstreetmap",
        "fetched_at": now.isoformat(), "elements_received": len(payload.get("elements", [])),
        "records_normalized": len(rows), **persisted, "duplicates_collapsed": duplicates,
        "invalid_or_unsupported_count": len(invalid), "invalid_ids": invalid[:100],
        "failed": False,
    }


def run_ingestion_job(db: Session, destination: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    key = destination.strip().lower()
    if key not in DESTINATIONS:
        raise ValueError("Only Jaipur and Udaipur ingestion is enabled.")
    job = AttractionIngestionJob(destination=DESTINATIONS[key]["name"], status="running")
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        summary = ingest_destination(db, key, client=client)
        job.status = "succeeded"
        job.completed_at = datetime.now(timezone.utc)
        job.summary = summary
        db.commit()
        return {"job_id": job.id, **summary}
    except Exception as exc:
        db.rollback()
        failed_job = db.get(AttractionIngestionJob, job.id)
        if failed_job is not None:
            failed_job.status = "failed"
            failed_job.completed_at = datetime.now(timezone.utc)
            failed_job.error_message = str(exc)[:500]
            db.commit()
        raise


def record_freshness(attraction: Attraction, now: datetime | None = None) -> str:
    fetched = attraction.last_fetched_at
    if fetched is None:
        return "unknown"
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return "fresh" if (now or datetime.now(timezone.utc)) - fetched <= FRESHNESS_TTL else "stale"


def to_optimizer_attraction(attraction: Attraction) -> dict[str, Any]:
    """Adapt internal catalog rows to the established optimizer input shape."""
    fee = attraction.curated_entrance_fee if attraction.curated_entrance_fee is not None else attraction.entrance_fee
    duration = (attraction.curated_visit_duration_minutes if attraction.curated_visit_duration_minutes is not None
                else attraction.visit_duration_minutes)
    hours = attraction.curated_opening_hours or attraction.opening_hours
    optimizer_category = {
        "historical": "history", "museum": "history", "religious": "spiritual",
        "park": "nature", "viewpoint": "nature", "cultural": "history",
        "entertainment": "entertainment", "other": "sightseeing",
    }.get(attraction.category.lower(), attraction.category.lower())
    priority_score, priority_reasons = attraction_priority(
        attraction.category, attraction.name, attraction.raw_tags or {}, attraction.verification_status
    )
    planning_window = _parse_simple_hours(attraction.curated_opening_hours)
    if planning_window is None:
        planning_window = _parse_simple_hours(attraction.opening_hours)
    assumed_duration = {
        "historical": 90, "museum": 90, "cultural": 75,
        "viewpoint": 45, "park": 60, "religious": 60,
        "entertainment": 120, "other": 60,
    }.get(attraction.category.lower(), 60)
    return {
        "id": attraction.id, "name": attraction.name, "category": optimizer_category,
        "catalog_category": attraction.category,
        "latitude": attraction.latitude, "longitude": attraction.longitude,
        "cost": fee if fee is not None else attraction.cost,
        "visit_minutes": duration if duration is not None else assumed_duration,
        "preference_score": attraction.preference_score, "weather_risk": attraction.weather_risk,
        "crowd_risk": attraction.crowd_risk, "availability_risk": attraction.availability_risk,
        "weather_risk_known": attraction.weather_risk_known, "crowd_risk_known": attraction.crowd_risk_known,
        "availability_risk_known": attraction.availability_risk_known, "risk_metadata": attraction.risk_metadata or {},
        "fatigue_score": attraction.fatigue_score,
        "opening_minute": planning_window[0] if planning_window else 540,
        "closing_minute": planning_window[1] if planning_window else 1140,
        "cost_known": fee is not None, "opening_hours": hours,
        "opening_window_known": planning_window is not None,
        "visit_duration_known": duration is not None,
        "data_source": attraction.data_source, "provider_name": attraction.provider_name,
        "source_dataset": attraction.source_dataset,
        "external_provider_id": attraction.external_provider_id, "source_url": attraction.source_url,
        "license_name": attraction.license_name, "attribution": attraction.attribution,
        "verification_status": attraction.verification_status,
        "last_fetched_at": attraction.last_fetched_at.isoformat() if attraction.last_fetched_at else None,
        "last_verified_at": attraction.last_verified_at.isoformat() if attraction.last_verified_at else None,
        "data_freshness": record_freshness(attraction), "raw_tags": attraction.raw_tags or {},
        "verification_notes": attraction.verification_notes,
        "priority_score": priority_score, "priority_reasons": priority_reasons,
    }
