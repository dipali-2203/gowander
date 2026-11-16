"""Transparent, configurable budget estimates for trips without live price providers."""

import os
from datetime import date
from math import ceil

from app.models import Trip
from app.schemas import AttractionInput, TripPlanningOptions
from app.services.routing import haversine_km


HOTEL_DEFAULTS = {
    "budget": 1800.0,
    "standard": 3800.0,
    "premium": 7800.0,
    "luxury": 15000.0,
}
MEAL_MULTIPLIERS = {"budget": 0.65, "standard": 1.0, "premium": 1.6, "luxury": 2.4}
PASSENGER_TRANSPORT = {"public transport", "bus", "train"}


def _configured_amount(key: str, fallback: float) -> float:
    raw = os.getenv(key)
    if raw is None:
        return fallback
    try:
        amount = float(raw)
    except ValueError:
        return fallback
    return max(0.0, amount)


def estimate_trip_budget(
    *,
    trip: Trip,
    days: list[dict],
    attractions: list[AttractionInput],
    data_source: str,
) -> dict:
    """Estimate fees and non-live travel/lodging/meal allowances in INR."""
    options = TripPlanningOptions.model_validate(trip.planning_options or {})
    traveler_count = options.traveler_count
    day_count = max(1, (trip.end_date - trip.start_date).days + 1)
    nights = max(0, (trip.end_date - trip.start_date).days)
    rooms = ceil(traveler_count / 2)
    by_id = {item.id: item for item in attractions}

    attraction_cost = round(sum(day["total_cost"] for day in days), 2)
    route_km = 0.0
    journey_count = 0
    for day in days:
        current = (trip.start_latitude, trip.start_longitude)
        for stop in day["stops"]:
            attraction = by_id.get(stop.attraction_id)
            if attraction is None:
                continue
            location = (attraction.latitude, attraction.longitude)
            route_km += haversine_km(current, location)
            journey_count += 1
            current = location

    mode = options.transportation_mode.strip().lower()
    normalized_mode = "public transport" if mode in {"metro", "transit"} else mode
    fare_rates = {
        "walking": 0.0,
        "public transport": 18.0,
        "bus": 12.0,
        "train": 20.0,
        "taxi": 25.0,
        "cab": 25.0,
        "car": 12.0,
        "private car": 12.0,
        "rental vehicle": 18.0,
        "mixed": 18.0,
    }
    default_rate = fare_rates.get(normalized_mode, fare_rates["mixed"])
    rate = _configured_amount(
        "TRIP_LOCAL_FARE_INR_PER_KM_" + "".join(ch if ch.isalnum() else "_" for ch in normalized_mode.upper()),
        default_rate,
    )
    fare_units = traveler_count if normalized_mode in PASSENGER_TRANSPORT else 1
    transportation = round(route_km * rate * fare_units, 2)

    hotel_default = HOTEL_DEFAULTS[options.accommodation_category]
    nightly_rate = _configured_amount(
        f"TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_{options.accommodation_category.upper()}",
        hotel_default,
    )
    accommodation = round(nights * rooms * nightly_rate, 2)

    meal_base_per_person_day = _configured_amount("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", 600.0)
    meal_multiplier = MEAL_MULTIPLIERS[options.accommodation_category]
    meals = round(day_count * traveler_count * meal_base_per_person_day * meal_multiplier, 2)
    miscellaneous = round(options.miscellaneous_budget, 2)
    total = round(attraction_cost + transportation + accommodation + meals + miscellaneous, 2)
    per_person = round(total / traveler_count, 2)
    daily_average = round(total / day_count, 2)
    budget_limit = round(trip.budget, 2)

    fallback_assumption = "Configurable development fallback estimate; not a quote or verified live price."
    categories = [
        {
            "key": "attractions", "label": "Attraction fees", "amount": attraction_cost,
            "source": data_source, "confidence": "catalog", "range_min": attraction_cost,
            "range_max": attraction_cost,
            "assumptions": ["Summed from scheduled attraction fee inputs."],
        },
        {
            "key": "transportation", "label": "Local transportation", "amount": transportation,
            "source": "configurable_estimate", "confidence": "low",
            "range_min": round(transportation * 0.75, 2), "range_max": round(transportation * 1.35, 2),
            "assumptions": [f"{route_km:.1f} km over {journey_count} estimated local legs at ₹{rate:g}/km for {options.transportation_mode}.", fallback_assumption],
        },
        {
            "key": "accommodation", "label": "Accommodation allowance", "amount": accommodation,
            "source": "configurable_estimate", "confidence": "low",
            "range_min": round(accommodation * 0.75, 2), "range_max": round(accommodation * 1.4, 2),
            "assumptions": [f"{nights} nights × {rooms} room(s) × ₹{nightly_rate:g}/room/night; two-person room occupancy assumption.", fallback_assumption],
        },
        {
            "key": "meals", "label": "Meals allowance", "amount": meals,
            "source": "configurable_estimate", "confidence": "low",
            "range_min": round(meals * 0.7, 2), "range_max": round(meals * 1.5, 2),
            "assumptions": [f"Three meals/day × {traveler_count} traveler(s) × {day_count} day(s); category multiplier {meal_multiplier:g}.", fallback_assumption],
        },
        {
            "key": "miscellaneous", "label": "Miscellaneous", "amount": miscellaneous,
            "source": "user_input", "confidence": "user_provided",
            "range_min": miscellaneous, "range_max": miscellaneous,
            "assumptions": ["Optional amount entered by the traveler."],
        },
    ]
    return {
        "currency": "INR",
        "total_estimated": total,
        "per_person": per_person,
        "daily_average": daily_average,
        "budget_limit": budget_limit,
        "remaining_budget": round(budget_limit - total, 2),
        "within_budget": total <= budget_limit + 1e-9,
        "categories": categories,
        "exclusions": [
            "Attraction fees use supplied catalog values; omitted fee fields may default to ₹0 and should be verified.",
            "Intercity travel to and from the destination is not priced because no route or fare provider is configured.",
            "No specific hotel, restaurant, availability, rating, or menu price is claimed.",
            "Transport estimates cover local planned legs and do not include parking or return travel to lodging.",
        ],
        "last_updated": None,
    }


def attraction_budget_after_fixed_costs(trip: Trip) -> float:
    """Reserve fallback lodging, meals and user-entered extras before attraction selection."""
    options = TripPlanningOptions.model_validate(trip.planning_options or {})
    day_count = max(1, (trip.end_date - trip.start_date).days + 1)
    nights = max(0, (trip.end_date - trip.start_date).days)
    rooms = ceil(options.traveler_count / 2)
    hotel_rate = _configured_amount(
        f"TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_{options.accommodation_category.upper()}",
        HOTEL_DEFAULTS[options.accommodation_category],
    )
    meal_rate = _configured_amount("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", 600.0)
    fixed = (
        nights * rooms * hotel_rate
        + day_count * options.traveler_count * meal_rate * MEAL_MULTIPLIERS[options.accommodation_category]
        + options.miscellaneous_budget
    )
    return max(0.0, trip.budget - fixed)
