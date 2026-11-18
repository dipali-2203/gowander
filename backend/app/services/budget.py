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


def _read(item, key: str, default=None):
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _accommodation_cost(trip: Trip, nights: int, rooms: int, options: TripPlanningOptions) -> tuple[float, float, str, str]:
    selected = getattr(trip, "accommodation_selection", None)
    hotel = getattr(selected, "hotel", None) if selected is not None else None
    if hotel is not None and hotel.nightly_price is not None and hotel.price_currency == "INR":
        nightly_rate = float(hotel.nightly_price)
        return (
            round(nights * rooms * nightly_rate, 2), nightly_rate,
            f"Selected property price from {hotel.price_source or hotel.provider_name}; {nights} nights, {rooms} room(s).",
            "source_tag",
        )
    category_rate = _configured_amount(
        f"TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_{options.accommodation_category.upper()}",
        HOTEL_DEFAULTS[options.accommodation_category],
    )
    luxury_factor = 0.7 + (options.luxury_level - 1) * 0.15
    allowance = round(nights * rooms * category_rate * luxury_factor, 2)
    assumption = (
        "Selected property has no supported INR nightly rate; retained the configured allowance. "
        if hotel is not None else ""
    ) + f"{nights} nights x {rooms} room(s) x INR {category_rate:g}/room/night x {luxury_factor:.2g} luxury factor; two-person room occupancy assumption."
    return allowance, category_rate, assumption, "low"


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

    attraction_cost = round(sum(float(_read(day, "total_cost", 0) or 0) for day in days), 2)
    scheduled_ids = {str(_read(stop, "attraction_id")) for day in days for stop in (_read(day, "stops", []) or [])}
    unknown_attraction_fees = sum(
        1 for item in attractions if item.id in scheduled_ids and item.cost_known is False
    )
    route_km = 0.0
    journey_count = 0
    for day in days:
        current = (trip.start_latitude, trip.start_longitude)
        for stop in (_read(day, "stops", []) or []):
            attraction = by_id.get(_read(stop, "attraction_id"))
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

    accommodation, nightly_rate, accommodation_assumption, accommodation_confidence = _accommodation_cost(
        trip, nights, rooms, options,
    )

    meal_base_per_person_day = _configured_amount("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", 600.0)
    meal_multiplier = MEAL_MULTIPLIERS[options.accommodation_category] * (0.8 + (options.luxury_level - 1) * 0.1)
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
            "key": "accommodation", "label": "Selected accommodation" if getattr(trip, "accommodation_selection", None) else "Accommodation allowance", "amount": accommodation,
            "source": "selected_hotel" if accommodation_confidence == "source_tag" else "configurable_estimate", "confidence": accommodation_confidence,
            "range_min": accommodation if accommodation_confidence == "source_tag" else round(accommodation * 0.75, 2),
            "range_max": accommodation if accommodation_confidence == "source_tag" else round(accommodation * 1.4, 2),
            "assumptions": [accommodation_assumption, fallback_assumption] if accommodation_confidence != "source_tag" else [accommodation_assumption],
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
        "is_complete": unknown_attraction_fees == 0,
        "unknown_attraction_fee_count": unknown_attraction_fees,
        "categories": categories,
        "exclusions": [
            "Intercity outbound and return travel are excluded because no route or fare provider is configured.",
            "Hotel amounts are configurable allowances, not actual booking prices or availability." if accommodation_confidence != "source_tag" else "The selected hotel's mapped nightly price is a sourced listing, not a booking quote or confirmation of availability.",
            "Meal amounts are configurable allowances; actual restaurant and menu prices are unavailable.",
            "Unknown attraction fees use an internal zero-cost optimizer placeholder; this does not mean entry is free.",
            "Parking, travel to or from lodging, and other unconfigured expenses may be excluded.",
        ],
        "last_updated": None,
    }


def attraction_budget_after_fixed_costs(trip: Trip) -> float:
    """Reserve fallback lodging, meals and user-entered extras before attraction selection."""
    options = TripPlanningOptions.model_validate(trip.planning_options or {})
    day_count = max(1, (trip.end_date - trip.start_date).days + 1)
    nights = max(0, (trip.end_date - trip.start_date).days)
    rooms = ceil(options.traveler_count / 2)
    hotel_cost, _, _, _ = _accommodation_cost(trip, nights, rooms, options)
    meal_rate = _configured_amount("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", 600.0)
    fixed = (
        hotel_cost
        + day_count * options.traveler_count * meal_rate * MEAL_MULTIPLIERS[options.accommodation_category] * (0.8 + (options.luxury_level - 1) * 0.1)
        + options.miscellaneous_budget
    )
    return max(0.0, trip.budget - fixed)
