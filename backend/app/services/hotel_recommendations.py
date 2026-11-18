"""Deterministic, explainable lodging scores from sourced hotel and trip data."""

from __future__ import annotations

import math
import os
from math import ceil
from typing import Any

from app.models import Hotel, Trip
from app.services.budget import HOTEL_DEFAULTS
from app.services.routing import haversine_km


DEFAULT_WEIGHTS = {
    "proximity": 0.50,
    "price": 0.25,
    "quality": 0.15,
    "preference": 0.07,
    "amenities": 0.03,
}


def _weights() -> dict[str, float]:
    result: dict[str, float] = {}
    for key, fallback in DEFAULT_WEIGHTS.items():
        try:
            value = float(os.getenv(f"HOTEL_RECOMMENDATION_WEIGHT_{key.upper()}", fallback))
        except (TypeError, ValueError):
            value = fallback
        result[key] = value if math.isfinite(value) and value > 0 else 0.0
    return result


def recommendation_weights() -> dict[str, float]:
    return _weights()


def planned_attraction_points(trip: Trip) -> list[tuple[float, float]]:
    """Resolve itinerary stop IDs to saved planner coordinates, preserving repeats."""
    itinerary = trip.latest_itinerary if isinstance(trip.latest_itinerary, dict) else {}
    planning = trip.planning_inputs if isinstance(trip.planning_inputs, dict) else {}
    candidates = planning.get("attractions", [])
    by_id = {
        str(item.get("id")): item
        for item in candidates
        if isinstance(item, dict) and item.get("id") is not None
    }
    points: list[tuple[float, float]] = []
    for day in itinerary.get("days", []) or []:
        if not isinstance(day, dict):
            continue
        for stop in day.get("stops", []) or []:
            if not isinstance(stop, dict):
                continue
            attraction = by_id.get(str(stop.get("attraction_id")))
            if attraction is None:
                continue
            try:
                lat, lon = float(attraction["latitude"]), float(attraction["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                points.append((lat, lon))
    return points


def _preference_score(hotel: Hotel, category: str) -> float | None:
    kind = hotel.hotel_type.lower()
    stars = hotel.stars
    if category == "budget":
        if stars is None and kind not in {"hostel", "guest_house", "motel"}:
            return None
        return 100.0 if kind in {"hostel", "guest_house", "motel"} or (stars is not None and stars <= 2) else 25.0
    if category in {"premium", "luxury"}:
        if stars is None and kind != "resort":
            return None
        threshold = 4 if category == "luxury" else 3
        return 100.0 if kind == "resort" or (stars is not None and stars >= threshold) else 25.0
    if category == "standard":
        if stars is None and kind not in {"hotel", "guest_house"}:
            return None
        return 100.0 if kind in {"hotel", "guest_house"} and (stars is None or 2 <= stars <= 4) else 50.0
    return None


def _amenity_score(hotel: Hotel, trip: Trip, preferences: dict[str, Any]) -> tuple[float | None, list[str]]:
    tags = hotel.raw_tags if isinstance(hotel.raw_tags, dict) else {}
    wanted: list[tuple[str, str]] = []
    meal_preferences = (trip.planning_options or {}).get("meal_preferences", [])
    if any("breakfast" in str(item).lower() for item in meal_preferences):
        wanted.append(("breakfast", "breakfast"))
    styles = [str(item).lower() for item in preferences.get("styles", [])]
    if any("family" in item for item in styles):
        wanted.extend([("hotel:family_rooms", "family rooms"), ("leisure", "family facilities")])
    if any("business" in item for item in styles):
        wanted.extend([("conference_room", "conference facilities"), ("office", "business facilities")])
    if not wanted:
        return None, []
    known = [(key, label) for key, label in wanted if key in tags]
    if not known:
        return None, []
    matched = [label for key, label in known if str(tags[key]).lower() not in {"no", "false", "0"}]
    return 100.0 * len(matched) / len(known), matched


def score_hotel(
    hotel: Hotel,
    trip: Trip,
    attraction_points: list[tuple[float, float]],
    user_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score only evidenced factors, renormalizing weights across available data."""
    preferences = user_preferences or {}
    options = trip.planning_options or {}
    factors: dict[str, float | None] = {key: None for key in DEFAULT_WEIGHTS}
    reasons: list[str] = []
    distances = [haversine_km((hotel.latitude, hotel.longitude), point) for point in attraction_points]
    average_distance = sum(distances) / len(distances) if distances else None
    nearest_distance = min(distances) if distances else None
    if average_distance is not None:
        factors["proximity"] = max(0.0, 100.0 * (1 - min(average_distance, 20.0) / 20.0))
        reasons.append(
            f"About {average_distance:.1f} km average straight-line distance from your {len(distances)} scheduled attraction visits."
        )

    nightly_rate = hotel.nightly_price
    if nightly_rate is not None and nightly_rate >= 0 and hotel.price_currency == "INR":
        category = options.get("accommodation_category", "standard")
        luxury_level = max(1, min(5, int(options.get("luxury_level", 3))))
        target = HOTEL_DEFAULTS.get(category, HOTEL_DEFAULTS["standard"]) * (0.7 + (luxury_level - 1) * 0.15)
        nights = max(0, (trip.end_date - trip.start_date).days)
        rooms = ceil(max(1, int(options.get("traveler_count", 1))) / 2)
        total_stay_price = nightly_rate * nights * rooms
        if nightly_rate == 0:
            factors["price"] = 100.0 if target == 0 else 0.0
        else:
            factors["price"] = max(0.0, 100.0 * (1 - abs(math.log(nightly_rate / max(target, 1))) / math.log(4)))
        if total_stay_price > trip.budget:
            factors["price"] = 0.0
            reasons.append("The listed stay total exceeds the entire saved trip budget.")
        if hotel.price_currency == "INR":
            reasons.append(f"Listed price ₹{nightly_rate:,.0f}/room/night compared with your configured accommodation allowance and total trip budget.")
        else:
            reasons.append("A sourced nightly price is available; it is not a booking quote.")

    if hotel.stars is not None and 0 <= hotel.stars <= 5:
        factors["quality"] = hotel.stars * 20.0
        reasons.append(f"OpenStreetMap has {hotel.stars:g} mapped hotel stars (classification, not guest reviews).")

    category_score = _preference_score(hotel, str(options.get("accommodation_category", "")))
    if category_score is not None:
        factors["preference"] = category_score
        reasons.append(f"Property type/classification was compared with your {options.get('accommodation_category')} accommodation preference.")

    amenity_score, matched_amenities = _amenity_score(hotel, trip, preferences)
    if amenity_score is not None:
        factors["amenities"] = amenity_score
        if matched_amenities:
            reasons.append("Mapped facilities support your preferences: " + ", ".join(matched_amenities) + ".")
        else:
            reasons.append("Mapped facilities did not confirm the requested amenity.")

    weights = _weights()
    used_weight = sum(weights[key] for key, value in factors.items() if value is not None)
    available_factor_count = sum(value is not None for value in factors.values())
    score = (
        sum(weights[key] * value for key, value in factors.items() if value is not None) / used_weight
        if used_weight > 0 and available_factor_count >= 2
        else None
    )
    return {
        "hotel": hotel,
        "score": round(score, 1) if score is not None else None,
        "score_confidence": "limited" if available_factor_count < 3 else "standard",
        "factor_scores": factors,
        "average_distance_km": round(average_distance, 2) if average_distance is not None else None,
        "nearest_distance_km": round(nearest_distance, 2) if nearest_distance is not None else None,
        "distance_kind": "straight_line" if distances else "unavailable",
        "reasons": reasons,
        "price_status": "sourced" if nightly_rate is not None else "unavailable",
        "rating_status": "unavailable",
        "amenities": list(hotel.amenities or []),
    }


def ranked_hotels(
    hotels: list[Hotel],
    trip: Trip,
    user_preferences: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    points = planned_attraction_points(trip)
    scored = [score_hotel(item, trip, points, user_preferences) for item in hotels]
    scored.sort(
        key=lambda item: (
            item["score"] is None,
            -(item["score"] or 0),
            item["average_distance_km"] is None,
            item["average_distance_km"] if item["average_distance_km"] is not None else math.inf,
            item["hotel"].name.casefold(),
            item["hotel"].id,
        )
    )
    labels: dict[str, str] = {}
    if scored and scored[0]["score"] is not None:
        labels[scored[0]["hotel"].id] = "Best overall match"
    nearest = min(
        (item for item in scored if item["average_distance_km"] is not None),
        key=lambda item: (item["average_distance_km"], item["hotel"].name.casefold(), item["hotel"].id),
        default=None,
    )
    if nearest is not None:
        labels.setdefault(nearest["hotel"].id, "Closest to itinerary")
    priced = [item for item in scored if item["hotel"].nightly_price is not None]
    if priced:
        cheapest = min(priced, key=lambda item: (item["hotel"].nightly_price, item["hotel"].name.casefold()))
        labels.setdefault(cheapest["hotel"].id, "Lowest sourced price")
    for item in scored:
        item["label"] = labels.get(item["hotel"].id)
    return scored


def serialize_hotel_recommendation(item: dict[str, Any]) -> dict[str, Any]:
    hotel: Hotel = item["hotel"]
    tags = hotel.raw_tags if isinstance(hotel.raw_tags, dict) else {}
    filters = []
    if hotel.hotel_type in {"hostel", "guest_house", "motel"} or (hotel.stars is not None and hotel.stars <= 2):
        filters.append("Budget")
    if hotel.hotel_type == "resort" or (hotel.stars is not None and hotel.stars >= 4):
        filters.append("Luxury")
    if any(str(tags.get(key, "")).lower() in {"yes", "true"} for key in ("hotel:family_rooms", "kids_area")):
        filters.append("Family")
    if any(str(tags.get(key, "")).lower() in {"yes", "true"} for key in ("conference_room", "business_center")):
        filters.append("Business")
    if str(tags.get("hotel:couples", "")).lower() in {"yes", "true"}:
        filters.append("Couples")
    return {
        "id": hotel.id,
        "name": hotel.name,
        "destination": hotel.destination,
        "hotel_type": hotel.hotel_type,
        "latitude": hotel.latitude,
        "longitude": hotel.longitude,
        "stars": hotel.stars,
        "amenities": list(hotel.amenities or []),
        "address": hotel.address,
        "website": hotel.website,
        "phone": hotel.phone,
        "brand": hotel.brand,
        "nightly_price": hotel.nightly_price,
        "price_currency": hotel.price_currency,
        "price_source": hotel.price_source,
        "price_status": item["price_status"],
        "rating_status": item["rating_status"],
        "score": item["score"],
        "score_confidence": item["score_confidence"],
        "factor_scores": item["factor_scores"],
        "average_distance_km": item["average_distance_km"],
        "nearest_distance_km": item["nearest_distance_km"],
        "distance_kind": item["distance_kind"],
        "reasons": item["reasons"],
        "label": item["label"],
        "filter_tags": filters,
        "source": hotel.provider_name,
        "source_dataset": hotel.source_dataset,
        "source_url": hotel.source_url,
        "license_name": hotel.license_name,
        "attribution": hotel.attribution,
        "last_fetched_at": hotel.last_fetched_at.isoformat() if hotel.last_fetched_at else None,
    }


def selected_accommodation_payload(trip: Trip) -> dict[str, Any] | None:
    selection = trip.accommodation_selection
    hotel = selection.hotel if selection is not None else None
    if hotel is None:
        return None
    return {
        "hotel_id": hotel.id,
        "name": hotel.name,
        "hotel_type": hotel.hotel_type,
        "nightly_price": hotel.nightly_price,
        "price_currency": hotel.price_currency,
        "price_source": hotel.price_source,
        "price_status": "sourced" if hotel.nightly_price is not None else "unavailable",
        "destination": hotel.destination,
        "source_url": hotel.source_url,
        "source_dataset": hotel.source_dataset,
        "attribution": hotel.attribution,
    }
