"""Transparent, configurable budget estimates for trips without live price providers."""

import json
import os
from datetime import date
from math import ceil, isfinite
from pathlib import Path

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
_BUDGET_ESTIMATES_PATH = Path(__file__).parents[1] / "data" / "budget_estimates.json"


def _budget_estimates() -> dict:
    with _BUDGET_ESTIMATES_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def _fee_range_for_attraction(item, estimates: dict, traveler_count: int) -> dict | None:
    """Return an explicitly priced fee; never infer price basis from optimizer cost."""
    fee_status = _read(item, "fee_status")
    currency = str(_read(item, "fee_currency", "") or "").upper()
    basis = _read(item, "fee_pricing_basis")
    amount = _read(item, "cost")
    if (fee_status == "verified" and _read(item, "cost_known") is True
            and currency == "INR" and basis in {"per_person", "group"}
            and isinstance(amount, (int, float)) and isfinite(amount) and amount >= 0):
        total = float(amount) * traveler_count if basis == "per_person" else float(amount)
        return {"lower": total, "representative": total, "upper": total,
                "status": "verified", "estimate_type": "verified",
                "estimate_category": None,
                "source": _read(item, "fee_source") or "Verified attraction fee",
                "assumptions": [
                    f"Verified INR amount priced {basis.replace('_', ' ')} and converted to a whole-group total for {traveler_count} traveler(s).",
                    *list(_read(item, "fee_assumptions", []) or []),
                ]}

    raw_tags = _read(item, "raw_tags", {}) or {}
    fee_tag = str(raw_tags.get("fee", "")).strip().lower() if isinstance(raw_tags, dict) else ""
    version = str(estimates.get("version", "unspecified"))
    if fee_tag in {"no", "false", "0"}:
        return {
            "lower": 0.0, "representative": 0.0, "upper": 0.0,
            "status": "estimated", "estimate_type": "source_tag",
            "estimate_category": None, "source": "osm_fee_tag",
            "estimate_version": version,
            "assumptions": [
                "OpenStreetMap fee=no is treated as a zero admission-fee estimate; this is not independently verified and does not cover incidental expenses.",
                f"Budget estimation rules version {version}.",
            ],
        }

    specific = estimates.get("attraction_specific_estimates", {}).get(str(_read(item, "id")))
    category = str(_read(item, "catalog_category") or _read(item, "category") or "").lower()
    if category == "other" and isinstance(raw_tags, dict):
        historic = str(raw_tags.get("historic", "")).strip().lower()
        heritage = str(raw_tags.get("heritage", "")).strip().lower()
        if historic not in {"", "no", "false", "0"} or heritage not in {"", "no", "false", "0"}:
            category = "historical"
    category_allowed = category in set(estimates.get("paid_admission_categories", []))
    category_requires_fee_tag = estimates.get("category_estimates_require_fee_yes", True)
    category_has_paid_tag = fee_tag in {"yes", "true", "1"}
    category_candidate = estimates.get("attraction_fee_category_estimates", {}).get(category)
    candidate = specific or (
        category_candidate
        if category_allowed and (not category_requires_fee_tag or category_has_paid_tag)
        else None
    )
    if not candidate:
        return None
    pricing_basis = candidate.get("pricing_basis", estimates.get("attraction_fee_pricing_basis"))
    currency = candidate.get("currency", estimates.get("currency"))
    if currency != "INR" or pricing_basis not in ("per_person", "group"):
        return None
    factor = traveler_count if pricing_basis == "per_person" else 1
    try:
        values = {key: float(candidate[key]) * factor for key in ("lower", "representative", "upper")}
    except (KeyError, TypeError, ValueError):
        return None
    if (not all(isfinite(value) for value in values.values()) or values["lower"] < 0
            or not values["lower"] <= values["representative"] <= values["upper"]):
        return None
    is_specific = specific is not None
    return {**values, "status": "estimated", "estimate_version": version,
            "estimate_type": "attraction_specific" if is_specific else "category",
            "estimate_category": category if not is_specific else None,
            "source": "versioned_attraction_specific_assumption" if is_specific else "versioned_category_assumption",
            "assumptions": [
                "Unverified attraction-specific planning assumption; not an official price." if is_specific else
                "Unverified category-level planning assumption; not an official attraction price.",
                f"INR {pricing_basis.replace('_', ' ')}; actual fees may differ.",
                *list(candidate.get("assumptions", []) or []),
            ]}


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
    by_id = {str(item.id): item for item in attractions}

    attraction_cost = round(sum(float(_read(day, "total_cost", 0) or 0) for day in days), 2)
    scheduled_ids = {str(_read(stop, "attraction_id")) for day in days
                     for stop in (_read(day, "stops", []) or [])
                     if _read(stop, "attraction_id") is not None}
    scheduled_items = [by_id.get(attraction_id) for attraction_id in sorted(scheduled_ids)]
    unknown_attraction_fees = sum(
        1 for item in scheduled_items if item is None or _read(item, "cost_known") is not True
    )
    estimate_config = _budget_estimates()
    stop_names = {
        str(_read(stop, "attraction_id")): _read(stop, "name")
        for day in days for stop in (_read(day, "stops", []) or [])
        if _read(stop, "attraction_id") is not None
    }
    fee_details = []
    for attraction_id, item in zip(sorted(scheduled_ids), scheduled_items):
        fee = _fee_range_for_attraction(item, estimate_config, traveler_count) if item is not None else None
        if fee is None:
            fee_details.append({
                "attraction_id": attraction_id,
                "name": _read(item, "name") if item is not None else stop_names.get(attraction_id),
                "category": _read(item, "catalog_category") or _read(item, "category") if item is not None else None,
                "original_fee_available": item is not None and _read(item, "cost_known") is True,
                "original_fee_amount": _read(item, "cost") if item is not None and _read(item, "cost_known") is True else None,
                "original_fee_currency": _read(item, "fee_currency") if item is not None else None,
                "original_fee_pricing_basis": _read(item, "fee_pricing_basis") if item is not None else None,
                "original_fee_status": _read(item, "fee_status") if item is not None else None,
                "status": "unavailable", "estimate_type": "unresolved",
                "lower": None, "representative": None, "upper": None,
                "currency": "INR", "source": None,
                "assumptions": ["No verified fee or configured attraction-specific/category estimate is available."],
            })
        else:
            fee_details.append({
                **fee,
                "attraction_id": attraction_id,
                "name": _read(item, "name"),
                "category": _read(item, "catalog_category") or _read(item, "category"),
                "original_fee_available": _read(item, "cost_known") is True,
                "original_fee_amount": _read(item, "cost") if _read(item, "cost_known") is True else None,
                "original_fee_currency": _read(item, "fee_currency"),
                "original_fee_pricing_basis": _read(item, "fee_pricing_basis"),
                "original_fee_status": _read(item, "fee_status"),
                "currency": "INR",
            })
    resolved_fee_details = [fee for fee in fee_details if fee["status"] != "unavailable"]
    unresolved_attraction_fees = len(fee_details) - len(resolved_fee_details)
    verified_fee_amount = round(sum(fee["representative"] for fee in resolved_fee_details
                                    if fee["status"] == "verified"), 2)
    estimated_fee_amount = round(sum(fee["representative"] for fee in resolved_fee_details
                                     if fee["status"] == "estimated"), 2)
    verified_fee_count = sum(fee["status"] == "verified" for fee in resolved_fee_details)
    estimated_fee_count = sum(fee["status"] == "estimated" for fee in resolved_fee_details)
    attraction_fee_amount = round(verified_fee_amount + estimated_fee_amount, 2)
    attraction_fee_min = round(sum(fee["lower"] for fee in resolved_fee_details), 2)
    attraction_fee_max = round(sum(fee["upper"] for fee in resolved_fee_details), 2)

    # Attribute each unique attraction fee to its first scheduled day. This keeps
    # repeated stop IDs from inflating either the trip total or the daily chart.
    daily_attraction_fees = []
    counted_fee_ids: set[str] = set()
    fee_by_id = {fee["attraction_id"]: fee for fee in fee_details}
    for day in days:
        unique_day_ids = list(dict.fromkeys(
            str(_read(stop, "attraction_id"))
            for stop in (_read(day, "stops", []) or [])
            if _read(stop, "attraction_id") is not None
        ))
        day_fees = []
        for attraction_id in unique_day_ids:
            if attraction_id in counted_fee_ids:
                continue
            counted_fee_ids.add(attraction_id)
            day_fees.append(fee_by_id[attraction_id])
        verified_total = round(sum(
            fee["representative"] for fee in day_fees if fee["status"] == "verified"
        ), 2)
        estimated_fees = [fee for fee in day_fees if fee["status"] == "estimated"]
        estimated_lower = round(sum(fee["lower"] for fee in estimated_fees), 2)
        estimated_representative = round(sum(fee["representative"] for fee in estimated_fees), 2)
        estimated_upper = round(sum(fee["upper"] for fee in estimated_fees), 2)
        unresolved_count = sum(fee["status"] == "unavailable" for fee in day_fees)
        fee_counted = len(day_fees)
        if not unique_day_ids:
            day_status = "no_attractions"
        elif not day_fees:
            day_status = "already_counted"
        elif unresolved_count and not (verified_total or estimated_fees):
            day_status = "unavailable"
        elif unresolved_count:
            day_status = "partial"
        elif estimated_fees:
            day_status = "estimated"
        else:
            day_status = "verified"
        daily_attraction_fees.append({
            "day_number": _read(day, "day_number"),
            "date": str(_read(day, "date", "") or ""),
            "scheduled_unique_attraction_count": len(unique_day_ids),
            "fee_counted_attraction_count": fee_counted,
            "verified_fee_total": verified_total,
            "estimated_fee_lower_total": estimated_lower,
            "estimated_fee_representative_total": estimated_representative,
            "estimated_fee_upper_total": estimated_upper,
            "representative_total": round(verified_total + estimated_representative, 2),
            "lower_total": round(verified_total + estimated_lower, 2),
            "upper_total": round(verified_total + estimated_upper, 2),
            "unresolved_attraction_count": unresolved_count,
            "currency": "INR", "status": day_status,
            "assumptions": (["Each attraction ID is charged once per trip and assigned to its first scheduled day."]
                            if day_fees else ["No additional attraction fee is allocated on this day." if unique_day_ids
                                              else "No attractions are scheduled on this day."]),
            "attractions": day_fees,
        })
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
    meals = round(day_count * traveler_count * meal_base_per_person_day, 2)
    # Preserve the legacy destination-only total semantics.
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
            "assumptions": [f"Configured default INR {meal_base_per_person_day:g} per traveler per day x {traveler_count} traveler(s) x {day_count} trip day(s); independent of accommodation tier.", fallback_assumption],
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
    attraction_status = (
        "partial" if unresolved_attraction_fees else
        "estimated" if estimated_fee_count else "verified"
    )
    attraction_assumptions = [
        "One fee is counted per unique scheduled attraction ID; optimizer cost placeholders are not used.",
    ]
    if estimated_fee_count:
        specific_count = sum(fee["estimate_type"] == "attraction_specific" for fee in resolved_fee_details)
        category_count = sum(fee["estimate_type"] == "category" for fee in resolved_fee_details)
        if specific_count:
            attraction_assumptions.append(
                f"{specific_count} attraction fee(s) use versioned, unverified attraction-specific assumptions."
            )
        if category_count:
            attraction_assumptions.append(
                f"{category_count} attraction fee(s) use versioned, unverified category assumptions."
            )
    if unresolved_attraction_fees:
        attraction_assumptions.append(
            f"{unresolved_attraction_fees} scheduled attraction fee(s) remain unresolved and are excluded from the subtotal."
        )
    attraction_assumptions.extend(dict.fromkeys(
        assumption for fee in resolved_fee_details for assumption in fee["assumptions"]
    ))
    estimate_types = {fee["estimate_type"] for fee in resolved_fee_details}
    if estimated_fee_count and verified_fee_count:
        fee_source = "verified_and_versioned_estimates"
    elif "attraction_specific" in estimate_types and "category" in estimate_types:
        fee_source = "versioned_attraction_and_category_estimates"
    elif "attraction_specific" in estimate_types:
        fee_source = "versioned_attraction_specific_assumption"
    elif "category" in estimate_types:
        fee_source = "versioned_category_assumption"
    elif verified_fee_amount or "verified" in estimate_types:
        fee_source = "verified_fee_data"
    else:
        fee_source = "no_scheduled_fees"
    fees_category = {
        "key": "attraction_fees", "label": "Attraction fees",
        "amount": attraction_fee_amount if resolved_fee_details or not scheduled_ids else None,
        "currency": "INR", "status": attraction_status,
        "source": fee_source,
        "range_min": attraction_fee_min if resolved_fee_details or not scheduled_ids else None,
        "range_max": attraction_fee_max if resolved_fee_details or not scheduled_ids else None,
        "verified_amount": verified_fee_amount, "estimated_amount": estimated_fee_amount,
        "verified_count": verified_fee_count,
        "estimated_count": estimated_fee_count,
        "unresolved_count": unresolved_attraction_fees,
        "sources": list(dict.fromkeys(fee["source"] for fee in resolved_fee_details)),
        "estimate_config_version": estimate_config["version"],
        "assumptions": attraction_assumptions,
    }

    misc_mode = options.miscellaneous_budget_mode
    if misc_mode is None:
        misc_mode = "manual" if options.miscellaneous_budget > 0 else "automatic"
    if misc_mode == "manual":
        misc_category = {"key": "miscellaneous", "label": "Miscellaneous",
                         "amount": round(options.miscellaneous_budget, 2), "currency": "INR",
                         "status": "user_provided", "source": "User input",
                         "range_min": round(options.miscellaneous_budget, 2),
                         "range_max": round(options.miscellaneous_budget, 2),
                         "assumptions": ["Traveler-provided whole-group amount; explicit zero is retained."]}
    elif misc_mode == "disabled":
        misc_category = {"key": "miscellaneous", "label": "Miscellaneous", "amount": None,
                         "currency": "INR", "status": "unavailable", "source": None,
                         "assumptions": ["Automatic contingency is disabled; no amount is assumed."]}
    base_categories = [
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
         "assumptions": [f"Configured default INR {meal_base_per_person_day:g} per traveler per day x {traveler_count} traveler(s) x {day_count} trip day(s); independent of accommodation tier.", fallback_assumption]},
        fees_category,
    ]
    if misc_mode == "automatic":
        percentages = estimate_config["miscellaneous_contingency_percentages"]
        base_amount = sum(float(item["amount"]) for item in base_categories if item.get("amount") is not None)
        base_min = sum(float(item.get("range_min") if item.get("range_min") is not None else item["amount"])
                       for item in base_categories if item.get("amount") is not None)
        base_max = sum(float(item.get("range_max") if item.get("range_max") is not None else item["amount"])
                       for item in base_categories if item.get("amount") is not None)
        base_incomplete = any(item["status"] in {"partial", "unavailable"} for item in base_categories)
        misc_amount = round(base_amount * percentages["representative"] / 100, 2)
        misc_category = {
            "key": "miscellaneous", "label": "Miscellaneous contingency", "amount": misc_amount,
            "currency": "INR", "status": "partial" if base_incomplete else "estimated",
            "estimated_amount": misc_amount,
            "source": "versioned_contingency_assumption",
            "estimate_config_version": estimate_config["version"],
            "range_min": round(base_min * percentages["lower"] / 100, 2),
            "range_max": round(base_max * percentages["upper"] / 100, 2),
            "assumptions": [
                "Whole-group contingency calculated from the other six budget categories; miscellaneous is excluded from its own base.",
                f"Versioned configurable rates: {percentages['lower']}% lower, {percentages['representative']}% representative, {percentages['upper']}% upper.",
                "The base contains unavailable or partial categories; this contingency covers only costs currently represented in that base." if base_incomplete else "Applied to the complete six-category base.",
            ],
        }
    complete_categories = [*base_categories, misc_category]
    known_subtotal = round(sum(
        item.get("verified_amount", item["amount"])
        for item in complete_categories
        if item.get("verified_amount") is not None or
        (item["amount"] is not None and item["status"] in {"verified", "user_provided"})
    ), 2)
    estimated_subtotal = round(sum(
        item.get("estimated_amount", item["amount"])
        for item in complete_categories
        if item.get("estimated_amount") is not None or
        (item["amount"] is not None and item["status"] == "estimated")
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
        "assumptions": [fallback_assumption, "Where a cost is estimated, feasibility checks use its upper range; displayed category amounts are representative estimates.", "partial_subtotal is an informational subtotal for partial categories and must not be added to known_subtotal or estimated_subtotal."],
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
        "is_complete": unresolved_attraction_fees == 0,
        "unknown_attraction_fee_count": unknown_attraction_fees,
        "unresolved_attraction_fee_count": unresolved_attraction_fees,
        "attraction_fee_details": fee_details,
        "daily_attraction_fees": daily_attraction_fees,
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


def estimate_saved_itinerary_budget(trip: Trip) -> dict | None:
    """Refresh a saved itinerary's estimate for API presentation without persisting it.

    The itinerary and its optimizer costs remain untouched. Stale trips keep their
    stored snapshot so the UI can continue to request itinerary regeneration.
    """
    itinerary = trip.latest_itinerary if isinstance(trip.latest_itinerary, dict) else None
    planning = trip.planning_inputs if isinstance(trip.planning_inputs, dict) else None
    if (
        itinerary is None
        or planning is None
        or trip.itinerary_stale
        or not isinstance(planning.get("attractions"), list)
        or not isinstance(itinerary.get("days"), list)
    ):
        return itinerary
    try:
        attractions = [AttractionInput.model_validate(item) for item in planning["attractions"]]
        estimate = estimate_trip_budget(
            trip=trip,
            days=itinerary["days"],
            attractions=attractions,
            data_source=planning.get("data_source") or itinerary.get("data_source") or "user_supplied",
        )
    except (KeyError, TypeError, ValueError):
        # Older persisted request snapshots may not contain fields required by
        # today's input schema; retain their original estimate in that case.
        return itinerary
    return {**itinerary, "budget_estimate": estimate}


def attraction_budget_after_fixed_costs(trip: Trip) -> float:
    """Reserve fallback lodging, meals and user-entered extras before attraction selection."""
    options = TripPlanningOptions.model_validate(trip.planning_options or {})
    day_count = max(1, (trip.end_date - trip.start_date).days + 1)
    nights = max(0, (trip.end_date - trip.start_date).days)
    rooms = ceil(options.traveler_count / 2)
    hotel_cost, _, _, _ = _accommodation_cost(trip, nights, rooms, options)
    meal_rate = _configured_amount("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", 600.0)
    misc_mode = options.miscellaneous_budget_mode
    misc_reserve = (
        options.miscellaneous_budget
        if misc_mode == "manual" or (misc_mode is None and options.miscellaneous_budget > 0)
        else 0.0
    )
    fixed = (
        hotel_cost
        + day_count * options.traveler_count * meal_rate
        + misc_reserve
    )
    for cost in (options.intercity_outbound_cost, options.intercity_return_cost):
        if cost is not None and cost.status != "unavailable" and cost.amount is not None and cost.currency == "INR":
            reserve = cost.range_max if cost.status == "estimated" and cost.range_max is not None else cost.amount
            fixed += float(reserve)
    return max(0.0, trip.budget - fixed)
