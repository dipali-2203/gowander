"""Public, read-only allowlisted view of itineraries shared by their owners."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Trip, TripShare
from app.services.weather import ATTRIBUTION as WEATHER_ATTRIBUTION
from app.services.trip_sharing import verify_share_token


router = APIRouter(prefix="/api/v1/shared", tags=["Shared itineraries"])


def _public_itinerary(trip: Trip) -> dict:
    itinerary = trip.latest_itinerary if isinstance(trip.latest_itinerary, dict) else {}
    planning = trip.planning_inputs if isinstance(trip.planning_inputs, dict) else {}
    options = trip.planning_options if isinstance(trip.planning_options, dict) else {}
    days = []
    for day in itinerary.get("days", []) or []:
        if not isinstance(day, dict):
            continue
        stops = []
        for stop in day.get("stops", []) or []:
            if not isinstance(stop, dict):
                continue
            arrival = int(stop.get("arrival_minute") or 0)
            departure = int(stop.get("departure_minute") or arrival)
            assessment = stop.get("weather_assessment")
            weather_advisories = []
            if isinstance(assessment, dict):
                for advisory in assessment.get("advisories", []) or []:
                    if isinstance(advisory, dict) and advisory.get("description"):
                        weather_advisories.append({
                            "type": str(advisory.get("type") or "weather"),
                            "description": str(advisory["description"]),
                            "condition": assessment.get("condition"),
                            "forecast_time": assessment.get("forecast_time"),
                        })
            stops.append({
                "name": str(stop.get("name") or "Activity"),
                "arrival_minute": arrival,
                "departure_minute": departure,
                "visit_minutes": max(0, departure - arrival),
                "travel_minutes_before": int(stop.get("travel_minutes_before") or 0),
                "weather_advisories": weather_advisories,
            })
        days.append({
            "day_number": day.get("day_number"),
            "date": str(day.get("date") or ""),
            "stops": stops,
            "meal_breaks": [
                {
                    "start_minute": int(item.get("start_minute") or 0),
                    "duration_minutes": int(item.get("duration_minutes") or 0),
                }
                for item in day.get("meal_breaks", []) or []
                if isinstance(item, dict)
            ],
            "total_travel_minutes": int(day.get("total_travel_minutes") or 0),
        })

    estimate = itinerary.get("budget_estimate")
    budget = None
    if isinstance(estimate, dict):
        budget = {
            "currency": "INR",
            "total_estimated": estimate.get("total_estimated"),
            "per_person": estimate.get("per_person"),
            "daily_average": estimate.get("daily_average"),
            "categories": [
                {"label": item.get("label"), "amount": item.get("amount")}
                for item in estimate.get("categories", []) or []
                if isinstance(item, dict)
            ],
            "exclusions": [str(item) for item in estimate.get("exclusions", []) or []],
        }

    attributions = list(dict.fromkeys(
        str(item["attribution"])
        for item in planning.get("attractions", []) or []
        if isinstance(item, dict) and item.get("attribution")
    ))
    if not attributions and any(
        isinstance(item, dict)
        and (item.get("data_source") == "osm" or item.get("provider_name") == "openstreetmap")
        for item in planning.get("attractions", []) or []
    ):
        attributions.append("© OpenStreetMap contributors · Open Database License (ODbL)")
    if any(
        isinstance(stop, dict) and isinstance(stop.get("weather_assessment"), dict)
        for day in itinerary.get("days", []) or [] if isinstance(day, dict)
        for stop in day.get("stops", []) or []
    ):
        attributions.append(WEATHER_ATTRIBUTION)

    return {
        "title": str(trip.name or trip.destination or "Shared itinerary"),
        "origin": str(trip.origin or ""),
        "destination": str(trip.destination or ""),
        "start_date": str(trip.start_date),
        "end_date": str(trip.end_date),
        "traveler_count": options.get("traveler_count"),
        "days": days,
        "budget_estimate": budget,
        "attributions": attributions,
    }


@router.get("/{token}")
def get_shared_itinerary(token: str, response: Response, db: Session = Depends(get_db)):
    public_id, separator, signature = token.partition(".")
    if not separator or not public_id or len(public_id) > 64 or len(signature) != 64:
        raise HTTPException(status_code=404, detail="Shared itinerary not found or no longer available.")
    share = db.query(TripShare).filter(TripShare.public_id == public_id).one_or_none()
    if (
        share is None
        or share.revoked_at is not None
        or not verify_share_token(token, share.trip_id, share.public_id)
    ):
        raise HTTPException(status_code=404, detail="Shared itinerary not found or no longer available.")
    trip = db.get(Trip, share.trip_id)
    if trip is None or not trip.latest_itinerary:
        raise HTTPException(status_code=404, detail="Shared itinerary not found or no longer available.")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return _public_itinerary(trip)
