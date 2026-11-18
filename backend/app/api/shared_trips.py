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
        complete = estimate.get("complete_budget")
        public_complete = None
        if isinstance(complete, dict):
            public_complete = {
                "schema_version": complete.get("schema_version"),
                "version": complete.get("version"),
                "currency": str(complete.get("currency") or "INR"),
                "categories": [
                    {
                        "key": str(item.get("key") or "unknown"),
                        "label": str(item.get("label") or item.get("key") or "Expense"),
                        "amount": item.get("amount") if isinstance(item.get("amount"), (int, float)) else None,
                        "currency": str(item.get("currency") or complete.get("currency") or "INR"),
                        "status": str(item.get("status") or "unavailable"),
                        "source": str(item["source"]) if item.get("source") else None,
                        "assumptions": [str(value) for value in item.get("assumptions", []) or []],
                        "confidence": item.get("confidence"),
                        "range_min": item.get("range_min"),
                        "range_max": item.get("range_max"),
                    }
                    for item in complete.get("categories", []) or []
                    if isinstance(item, dict)
                ],
                "known_subtotal": complete.get("known_subtotal"),
                "estimated_subtotal": complete.get("estimated_subtotal"),
                "partial_subtotal": complete.get("partial_subtotal"),
                "unavailable_categories": [str(value) for value in complete.get("unavailable_categories", []) or []],
                "partial_categories": [str(value) for value in complete.get("partial_categories", []) or []],
                "completeness": str(complete.get("completeness") or "incomplete"),
                "total_estimate": complete.get("total_estimate"),
                "budget_limit": complete.get("budget_limit"),
                "remaining_budget": complete.get("remaining_budget"),
                "within_budget": complete.get("within_budget"),
                "assumptions": [str(value) for value in complete.get("assumptions", []) or []],
                "exclusions": [str(value) for value in complete.get("exclusions", []) or []],
            }
        budget = {
            "currency": "INR",
            "total_estimated": estimate.get("total_estimated"),
            "per_person": estimate.get("per_person"),
            "daily_average": estimate.get("daily_average"),
            "budget_limit": estimate.get("budget_limit"),
            "remaining_budget": estimate.get("remaining_budget"),
            "within_budget": estimate.get("within_budget"),
            "is_complete": estimate.get("is_complete", False),
            "unknown_attraction_fee_count": estimate.get("unknown_attraction_fee_count", 0),
            "categories": [
                {
                    "key": str(item.get("key") or "unknown"),
                    "label": item.get("label"),
                    "amount": item.get("amount") if isinstance(item.get("amount"), (int, float)) else None,
                    "source": str(item.get("source") or "Unavailable"),
                    "confidence": str(item.get("confidence") or "unknown"),
                    "range_min": item.get("range_min", 0),
                    "range_max": item.get("range_max", 0),
                    "assumptions": [str(value) for value in item.get("assumptions", []) or []],
                }
                for item in estimate.get("categories", []) or []
                if isinstance(item, dict)
            ],
            "exclusions": [str(item) for item in estimate.get("exclusions", []) or []],
            "last_updated": estimate.get("last_updated"),
            "complete_budget": public_complete,
            "complete_budget_current": bool(not trip.itinerary_stale and public_complete),
            "estimate_is_current": not trip.itinerary_stale,
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
        "selected_accommodation": (
            {
                "name": trip.accommodation_selection.hotel.name,
                "hotel_type": trip.accommodation_selection.hotel.hotel_type,
                "address": trip.accommodation_selection.hotel.address,
                "nightly_price": trip.accommodation_selection.hotel.nightly_price,
                "price_currency": trip.accommodation_selection.hotel.price_currency,
                "price_source": trip.accommodation_selection.hotel.price_source,
                "source_url": trip.accommodation_selection.hotel.source_url,
                "source_dataset": trip.accommodation_selection.hotel.source_dataset,
                "attribution": trip.accommodation_selection.hotel.attribution,
            }
            if trip.accommodation_selection is not None
            and trip.accommodation_selection.hotel is not None
            else None
        ),
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
