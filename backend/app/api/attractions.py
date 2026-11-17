import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.data.catalog import SYNTHETIC_CATALOG, SYNTHETIC_START_LOCATIONS
from app.database import get_db
from app.models import Attraction, AttractionIngestionJob
from app.services.poi_catalog import DESTINATIONS, OSM_ATTRIBUTION, run_ingestion_job, to_optimizer_attraction

router = APIRouter(prefix="/api/v1/attractions", tags=["Attractions"])
logger = logging.getLogger(__name__)


def _allow_synthetic_fallback() -> bool:
    configured = os.getenv("POI_ALLOW_SYNTHETIC_FALLBACK")
    if configured is not None:
        return configured.strip().lower() in {"1", "true", "yes"}
    return os.getenv("APP_ENV", "development").strip().lower() not in {"production", "prod"}


def _require_admin_role(user) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")


def _require_ingestion_enabled() -> None:
    if os.getenv("POI_INGESTION_ENABLED", "false").strip().lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=503, detail="POI ingestion is disabled by configuration.")


@router.get("/catalog/{destination}")
def get_attraction_catalog(destination: str, db: Session = Depends(get_db)):
    normalized = destination.strip().lower()
    config = DESTINATIONS.get(normalized)
    if config is None:
        raise HTTPException(status_code=404, detail="No attraction catalog is configured for this destination.")
    records = db.scalars(
        select(Attraction)
        .where(Attraction.destination.ilike(config["name"]))
        .order_by(Attraction.name, Attraction.id)
    ).all()
    if records:
        sources = {item.data_source for item in records}
        data_source = next(iter(sources)) if len(sources) == 1 else "mixed"
        return {
            "destination": config["name"], "data_source": data_source,
            "catalog_status": "available", "message": None,
            "start_location": config["start"], "attribution": OSM_ATTRIBUTION if any(item.provider_name == "openstreetmap" for item in records) else None,
            "attractions": [to_optimizer_attraction(item) for item in records],
        }

    if _allow_synthetic_fallback():
        attractions = [item.model_dump(mode="json") | {
            "cost_known": False, "opening_hours": None, "visit_duration_known": False,
            "data_source": "synthetic", "provider_name": None, "external_provider_id": None,
            "source_url": None, "license_name": None, "attribution": None,
            "verification_status": "synthetic_unverified", "last_fetched_at": None,
            "last_verified_at": None, "data_freshness": "not_applicable", "raw_tags": {},
        } for item in SYNTHETIC_CATALOG[normalized]]
        return {
            "destination": config["name"], "data_source": "synthetic",
            "catalog_status": "synthetic_fallback",
            "message": "No imported OSM catalog is available. These development-only entries are synthetic and are not verified attraction data.",
            "start_location": SYNTHETIC_START_LOCATIONS.get(normalized), "attribution": None,
            "attractions": attractions,
        }
    return {
        "destination": config["name"], "data_source": "unavailable",
        "catalog_status": "not_ingested",
        "message": "Attraction data has not been imported for this destination yet.",
        "start_location": config["start"], "attribution": None, "attractions": [],
    }


class AttractionCreate(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=50)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    cost: float = Field(default=0, ge=0)
    visit_minutes: int = Field(default=60, gt=0)
    preference_score: float = Field(default=0.5, ge=0, le=1)
    weather_risk: float = Field(default=0, ge=0, le=1)
    crowd_risk: float = Field(default=0, ge=0, le=1)
    availability_risk: float = Field(default=0, ge=0, le=1)
    opening_minute: int = Field(default=540, ge=0, le=1439)
    closing_minute: int = Field(default=1020, ge=1, le=1440)
    data_source: str = Field(default="user_supplied", max_length=30)
    fatigue_score: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def validate_window(self):
        if self.closing_minute <= self.opening_minute:
            raise ValueError("closing_minute must be after opening_minute")
        return self


class AttractionVerificationUpdate(BaseModel):
    entrance_fee: float | None = Field(default=None, ge=0)
    opening_hours: str | None = Field(default=None, max_length=500)
    visit_duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = Field(default=None, max_length=500)


@router.post("", status_code=201)
def create_attraction(request: AttractionCreate, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    if db.get(Attraction, request.id) is not None:
        raise HTTPException(status_code=409, detail="An attraction with this ID already exists.")
    attraction = Attraction(**request.model_dump(), verification_status="unverified")
    db.add(attraction)
    db.commit()
    db.refresh(attraction)
    return attraction


@router.get("")
def list_attractions(destination: str, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    return db.scalars(
        select(Attraction).where(Attraction.destination.ilike(destination.strip())).order_by(Attraction.name)
    ).all()


@router.get("/admin/ingestion-jobs")
def list_ingestion_jobs(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_admin_role(user)
    jobs = db.scalars(select(AttractionIngestionJob).order_by(AttractionIngestionJob.started_at.desc()).limit(limit)).all()
    return [{"id": job.id, "destination": job.destination, "provider_name": job.provider_name,
             "status": job.status, "started_at": job.started_at, "completed_at": job.completed_at,
             "summary": job.summary, "error_message": job.error_message} for job in jobs]


@router.post("/admin/ingest/{destination}", status_code=202)
def ingest_attractions(destination: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_admin_role(user)
    _require_ingestion_enabled()
    try:
        return run_ingestion_job(db, destination)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Attraction ingestion failed for %s", destination)
        raise HTTPException(status_code=502, detail="Attraction ingestion failed. Review the recorded ingestion job.") from exc


@router.patch("/admin/{attraction_id}/verify")
def verify_attraction(attraction_id: str, request: AttractionVerificationUpdate,
                      db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_admin_role(user)
    attraction = db.get(Attraction, attraction_id)
    if attraction is None:
        raise HTTPException(status_code=404, detail="Attraction not found.")
    fields = request.model_fields_set
    if not fields.intersection({"entrance_fee", "opening_hours", "visit_duration_minutes"}):
        raise HTTPException(status_code=422, detail="At least one curated planning field is required.")
    if "entrance_fee" in fields:
        attraction.curated_entrance_fee = request.entrance_fee
    if "opening_hours" in fields:
        attraction.curated_opening_hours = request.opening_hours
    if "visit_duration_minutes" in fields:
        attraction.curated_visit_duration_minutes = request.visit_duration_minutes
    attraction.last_verified_at = datetime.now(timezone.utc)
    attraction.verification_status = "manually_verified"
    if request.confidence is not None:
        attraction.data_confidence = request.confidence
    if "notes" in fields:
        attraction.verification_notes = request.notes
    db.commit()
    db.refresh(attraction)
    return to_optimizer_attraction(attraction) | {"verification_notes": request.notes}


@router.get("/{attraction_id}")
def get_attraction(attraction_id: str, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    attraction = db.get(Attraction, attraction_id)
    if attraction is None:
        raise HTTPException(status_code=404, detail="Attraction not found.")
    return attraction
