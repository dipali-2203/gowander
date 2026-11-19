"""Transparent, configurable budget estimates for trips without live price providers."""

import os
from datetime import date
from math import ceil

from app.models import Trip
from app.schemas import AttractionInput, TripPlanningOptions
from app.services.routing import haversine_km
from app.services.transportation_estimator import local_transport_cost


HOTEL_DEFAULTS = {
    "budget": 1800.0,
    "standard": 3800.0,
    "premium": 7800.0,
    "luxury": 15000.0,
}
MEAL_MULTIPLIERS = {"budget": 0.65, "standard": 1.0, "premium": 1.6, "luxury": 2.4}


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

    local_cost = local_transport_cost(route_km, journey_count, options.transportation_mode, traveler_count)
    transportation = local_cost.get("amount")

    accommodation, nightly_rate, accommodation_assumption, accommodation_confidence = _accommodation_cost(
        trip, nights, rooms, options,
    )

    meal_base_per_person_day = _configured_amount("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", 600.0)
    meal_multiplier = MEAL_MULTIPLIERS[options.accommodation_category] * (0.8 + (options.luxury_level - 1) * 0.1)
    meals = round(day_count * traveler_count * meal_base_per_person_day * meal_multiplier, 2)
    miscellaneous = round(options.miscellaneous_budget, 2)
    # This legacy total intentionally retains destination-only semantics for old
    # API/UI consumers. The versioned complete-budget object below is authoritative
    # for complete-journey totals.
    total = round(attraction_cost + (transportation or 0.0) + accommodation + meals + miscellaneous, 2)
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
            "source": local_cost.get("source", "configurable_estimate"), "confidence": "low",
            "range_min": local_cost.get("range_min"), "range_max": local_cost.get("range_max"),
            "assumptions": [*local_cost.get("assumptions", []), fallback_assumption],
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
    legacy_categories = categories

    def intercity_category(key: str, label: str, item) -> dict:
        if item is None:
            item = {"status": "unavailable", "amount": None, "currency": "INR"}
        amount = _read(item, "amount")
        currency = str(_read(item, "currency", "INR") or "INR").upper()
        status = _read(item, "status", "unavailable")
        source = _read(item, "source")
        assumptions = list(_read(item, "assumptions", []) or [])
        if currency != "INR":
            status = "unavailable"
            amount = None
            assumptions.append(f"{currency} intercity costs cannot be converted to INR in this phase.")
        if status == "unavailable" or amount is None:
            return {
                "key": key, "label": label, "amount": None, "currency": currency,
                "status": "unavailable", "source": source, "assumptions": assumptions,
                "range_min": _read(item, "range_min"), "range_max": _read(item, "range_max"),
                "mode": _read(item, "mode"), "unit_basis": _read(item, "unit_basis"),
                "amount_basis": _read(item, "amount_basis"),
                "traveler_count": _read(item, "traveler_count"), "distance_km": _read(item, "distance_km"),
                "estimated_at": _read(item, "estimated_at"), "method": _read(item, "method"),
            }
        return {
            "key": key, "label": label, "amount": round(float(amount), 2),
            "currency": "INR", "status": status, "source": source,
            "assumptions": assumptions,
            "range_min": _read(item, "range_min"), "range_max": _read(item, "range_max"),
            "mode": _read(item, "mode"), "unit_basis": _read(item, "unit_basis"),
            "amount_basis": _read(item, "amount_basis"),
            "traveler_count": _read(item, "traveler_count"), "distance_km": _read(item, "distance_km"),
            "estimated_at": _read(item, "estimated_at"), "method": _read(item, "method"),
        }

    outbound = intercity_category(
        "intercity_outbound", "Intercity transportation · outbound", options.intercity_outbound_cost,
    )
    returning = intercity_category(
        "intercity_return", "Intercity transportation · return", options.intercity_return_cost,
    )
    attraction_status = "partial" if unknown_attraction_fees else "estimated"
    misc_category = (
        {"key": "miscellaneous", "label": "Miscellaneous", "amount": miscellaneous,
         "currency": "INR", "status": "user_provided", "source": "User input",
         "assumptions": ["Optional traveler-entered allowance."]}
        if options.miscellaneous_budget > 0 else
        {"key": "miscellaneous", "label": "Miscellaneous", "amount": None,
         "currency": "INR", "status": "unavailable", "source": None,
         "assumptions": ["No miscellaneous allowance was provided; it is not treated as a verified zero cost."]}
    )
    complete_categories = [
        outbound,
        returning,
        {"key": "local_transport", "label": "Local transportation", "amount": transportation,
         "currency": "INR", "status": local_cost.get("status", "unavailable"),
         "source": local_cost.get("source", "configurable_distance_estimate"),
         "confidence": "low", "range_min": local_cost.get("range_min"),
         "range_max": local_cost.get("range_max"), "mode": local_cost.get("mode", options.transportation_mode),
         "unit_basis": local_cost.get("unit_basis"), "amount_basis": local_cost.get("amount_basis"),
         "assumptions": [*local_cost.get("assumptions", []), fallback_assumption]},
        {"key": "accommodation", "label": "Accommodation", "amount": accommodation,
         "currency": "INR", "status": "estimated", "source": "selected_hotel_listing" if accommodation_confidence == "source_tag" else "configurable_allowance",
         "confidence": accommodation_confidence,
         "range_min": accommodation if accommodation_confidence == "source_tag" else round(accommodation * 0.75, 2),
         "range_max": accommodation if accommodation_confidence == "source_tag" else round(accommodation * 1.4, 2),
         "assumptions": [accommodation_assumption]},
        {"key": "food", "label": "Food", "amount": meals, "currency": "INR",
         "status": "estimated", "source": "configurable_allowance", "confidence": "low",
         "range_min": round(meals * 0.7, 2), "range_max": round(meals * 1.5, 2),
         "assumptions": [f"Three meals/day × {traveler_count} traveler(s) × {day_count} day(s); category multiplier {meal_multiplier:g}.", fallback_assumption]},
        {"key": "attraction_fees", "label": "Attraction fees", "amount": attraction_cost,
         "currency": "INR", "status": attraction_status, "source": data_source,
         "assumptions": ["Summed scheduled catalog fee inputs."] + ([f"{unknown_attraction_fees} scheduled fee(s) are unknown; this is only a partial subtotal."] if unknown_attraction_fees else [])},
        misc_category,
    ]
    known_subtotal = round(sum(
        item["amount"] for item in complete_categories
        if item["amount"] is not None and item["status"] in {"verified", "user_provided"}
    ), 2)
    estimated_subtotal = round(sum(
        item["amount"] for item in complete_categories
        if item["amount"] is not None and item["status"] == "estimated"
    ), 2)
    partial_subtotal = round(sum(
        item["amount"] for item in complete_categories
        if item["amount"] is not None and item["status"] == "partial"
    ), 2)
    incomplete_categories = [
        item["key"] for item in complete_categories
        if item["status"] in {"partial", "unavailable"}
    ]
    complete_total = None if incomplete_categories else round(known_subtotal + estimated_subtotal, 2)
    total_range_min = None if incomplete_categories else round(sum(
        item.get("range_min") if isinstance(item.get("range_min"), (int, float)) else item["amount"]
        for item in complete_categories if item["amount"] is not None
    ), 2)
    total_range_max = None if incomplete_categories else round(sum(
        item.get("range_max") if isinstance(item.get("range_max"), (int, float)) else item["amount"]
        for item in complete_categories if item["amount"] is not None
    ), 2)
    within_budget = None if complete_total is None or total_range_max is None else total_range_max <= budget_limit + 1e-9
    completeness = "complete" if not incomplete_categories else ("partial" if known_subtotal + estimated_subtotal + partial_subtotal > 0 else "unavailable")
    complete_budget = {
        "schema_version": 2,
        "currency": "INR",
        "categories": complete_categories,
        "known_subtotal": known_subtotal,
        "estimated_subtotal": estimated_subtotal,
        "partial_subtotal": partial_subtotal,
        "unavailable_categories": [item["key"] for item in complete_categories if item["status"] == "unavailable"],
        "partial_categories": [item["key"] for item in complete_categories if item["status"] == "partial"],
        "completeness": completeness,
        "total_estimate": complete_total,
        "total_estimate_range_min": total_range_min,
        "total_estimate_range_max": total_range_max,
        "budget_limit": budget_limit,
        "remaining_budget": round(budget_limit - total_range_max, 2) if total_range_max is not None else None,
        "within_budget": within_budget,
        "assumptions": [fallback_assumption, "Where a cost is estimated, the budget allocation and feasibility check use its upper range; displayed category amounts are representative estimates."],
        "exclusions": ["Unknown or partial categories are not added as zero to the complete total."],
    }
    return {
        "budget_schema_version": 2,
        "complete_budget": complete_budget,
        "currency": "INR",
        "total_estimated": total,
        "per_person": per_person,
        "daily_average": daily_average,
        "budget_limit": budget_limit,
        "remaining_budget": round(budget_limit - total, 2),
        "within_budget": total <= budget_limit + 1e-9,
        "is_complete": unknown_attraction_fees == 0,
        "unknown_attraction_fee_count": unknown_attraction_fees,
        "categories": legacy_categories,
        "exclusions": [
            "The legacy destination-only total excludes intercity outbound and return expenses; see complete_budget for the versioned journey estimate.",
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
    for cost in (options.intercity_outbound_cost, options.intercity_return_cost):
        if cost is not None and cost.status != "unavailable" and cost.amount is not None and cost.currency == "INR":
            reserve = cost.range_max if cost.status == "estimated" and cost.range_max is not None else cost.amount
            fixed += float(reserve)
    return max(0.0, trip.budget - fixed)
