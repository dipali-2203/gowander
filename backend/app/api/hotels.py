"""Authenticated hotel recommendations and owner-only trip accommodation selection."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, require_allowed_origin
from app.database import get_db
from app.models import Hotel, Trip, TripAccommodation, User
from app.schemas import TripAccommodationRequest
from app.schemas import AttractionInput
from app.services.budget import estimate_trip_budget
from app.services.hotel_recommendations import (
    planned_attraction_points,
    recommendation_weights,
    ranked_hotels,
    selected_accommodation_payload,
    serialize_hotel_recommendation,
)


router = APIRouter(tags=["Hotels"])


def _owned_trip(trip_id: int, user: User, db: Session) -> Trip:
    trip = db.scalar(select(Trip).where(Trip.id == trip_id, Trip.owner_user_id == user.id))
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found.")
    return trip


@router.get("/api/v1/hotels/recommendations")
def get_hotel_recommendations(
    trip_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trip = _owned_trip(trip_id, user, db)
    points = planned_attraction_points(trip)
    if not (trip.latest_itinerary or {}).get("days") or not points:
        raise HTTPException(
            status_code=409,
            detail="Generate and save an itinerary with attraction locations to get route-aware hotel recommendations.",
        )
    hotels = db.scalars(
        select(Hotel).where(Hotel.destination.ilike(trip.destination)).order_by(Hotel.name, Hotel.id)
    ).all()
    ranked = ranked_hotels(hotels, trip, user.travel_preferences or {})
    selected = selected_accommodation_payload(trip)
    items = [serialize_hotel_recommendation(item) | {"selected": selected is not None and selected["hotel_id"] == item["hotel"].id}
             for item in ranked]
    return {
        "trip": {
            "id": trip.id,
            "name": trip.name,
            "destination": trip.destination,
            "start_date": str(trip.start_date),
            "end_date": str(trip.end_date),
            "nights": max(0, (trip.end_date - trip.start_date).days),
            "traveler_count": (trip.planning_options or {}).get("traveler_count"),
            "budget": trip.budget,
            "accommodation_category": (trip.planning_options or {}).get("accommodation_category"),
        },
        "planned_attraction_count": len(points),
        "distance_method": "straight_line_haversine",
        "score_method": "weighted_mean_of_available_factors",
        "score_note": "Available factor weights are renormalized to 100%; missing data is excluded rather than scored as a positive match. A score is withheld if fewer than two factors are known.",
        "factor_weights": recommendation_weights(),
        "items": items,
        "selected_accommodation": selected,
        "attribution": "© OpenStreetMap contributors" if any(item.provider_name == "openstreetmap" for item in hotels) else None,
    }


def _refresh_budget_for_selection(trip: Trip, db: Session) -> None:
    """Persist selected-property details and adjust an existing saved estimate, if present."""
    itinerary = trip.latest_itinerary
    if not isinstance(itinerary, dict) or not isinstance(itinerary.get("budget_estimate"), dict):
        return
    raw_inputs = (trip.planning_inputs or {}).get("attractions", [])
    attractions = []
    for item in raw_inputs:
        if isinstance(item, dict):
            try:
                attractions.append(AttractionInput.model_validate(item))
            except Exception:
                continue
    estimate = estimate_trip_budget(
        trip=trip,
        days=itinerary.get("days", []),
        attractions=attractions,
        data_source=str(itinerary.get("data_source") or "user_supplied"),
    )
    trip.latest_itinerary = {**itinerary, "budget_estimate": estimate}


@router.put("/api/v1/trips/{trip_id}/accommodation", dependencies=[Depends(require_allowed_origin)])
def select_trip_accommodation(
    trip_id: int,
    request: TripAccommodationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trip = _owned_trip(trip_id, user, db)
    hotel = db.get(Hotel, request.hotel_id)
    if hotel is None or hotel.destination.casefold() != str(trip.destination).casefold():
        raise HTTPException(status_code=404, detail="Hotel not found for this trip destination.")
    selection = db.get(TripAccommodation, trip.id)
    if selection is None:
        selection = TripAccommodation(trip_id=trip.id, hotel_id=hotel.id)
        db.add(selection)
    else:
        selection.hotel_id = hotel.id
    db.flush()
    _refresh_budget_for_selection(trip, db)
    trip.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(selection)
    return {
        "selected_accommodation": selected_accommodation_payload(trip),
        "latest_itinerary": trip.latest_itinerary,
    }


@router.delete("/api/v1/trips/{trip_id}/accommodation", dependencies=[Depends(require_allowed_origin)])
def remove_trip_accommodation(
    trip_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trip = _owned_trip(trip_id, user, db)
    selection = db.get(TripAccommodation, trip.id)
    if selection is None:
        raise HTTPException(status_code=404, detail="This trip has no selected accommodation.")
    db.delete(selection)
    db.flush()
    _refresh_budget_for_selection(trip, db)
    trip.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"selected_accommodation": None, "latest_itinerary": trip.latest_itinerary}
