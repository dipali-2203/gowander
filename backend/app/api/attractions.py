from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Attraction
from app.api.auth import get_current_user
from app.data.catalog import SYNTHETIC_CATALOG, SYNTHETIC_START_LOCATIONS

router = APIRouter(
    prefix="/api/v1/attractions",
    tags=["Attractions"],
)


@router.get("/catalog/{destination}")
def get_synthetic_catalog(destination: str):
    """Return a synthetic local planning catalog; it is never live data."""
    normalized = destination.strip().lower()
    return {
        "destination": destination,
        "data_source": "synthetic",
        "start_location": SYNTHETIC_START_LOCATIONS.get(normalized),
        "attractions": SYNTHETIC_CATALOG.get(normalized, []),
    }


class AttractionCreate(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=50)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    cost: float = Field(default=0, ge=0)
    visit_minutes: int = Field(gt=0)
    preference_score: float = Field(default=0.5, ge=0, le=1)
    weather_risk: float = Field(default=0, ge=0, le=1)
    crowd_risk: float = Field(default=0, ge=0, le=1)
    availability_risk: float = Field(default=0, ge=0, le=1)
    opening_minute: int = Field(default=540, ge=0, le=1439)
    closing_minute: int = Field(default=1020, ge=1, le=1440)
    data_source: str = Field(default="user_supplied", max_length=30)
    fatigue_score: float = Field(default=0.5, ge=0, le=1)


@router.post("", status_code=201)
def create_attraction(
    request: AttractionCreate,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    existing = db.get(Attraction, request.id)

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="An attraction with this ID already exists.",
        )

    attraction = Attraction(**request.model_dump())
    db.add(attraction)
    db.commit()
    db.refresh(attraction)

    return attraction


@router.get("")
def list_attractions(
    destination: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    attractions = (
        db.query(Attraction)
        .filter(
            Attraction.destination.ilike(destination.strip())
        )
        .order_by(Attraction.name)
        .all()
    )

    return attractions


@router.get("/{attraction_id}")
def get_attraction(
    attraction_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    attraction = db.get(Attraction, attraction_id)

    if attraction is None:
        raise HTTPException(
            status_code=404,
            detail="Attraction not found.",
        )

    return attraction
