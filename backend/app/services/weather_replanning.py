"""Build non-destructive, saved-trip forecast proposals."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any
from uuid import uuid4

from app.services.routing import estimate_minutes
from app.services.weather import ATTRIBUTION, PROVIDER, fetch_forecasts, forecast_at
from app.services.weather_risk import assess_weather_risk


def _scheduled(day_date: str, minute: int) -> datetime:
    hour, mins = divmod(int(minute), 60)
    return datetime.fromisoformat(f"{day_date}T{hour % 24:02d}:{mins:02d}:00")


def _is_indoor(activity: dict[str, Any]) -> bool:
    category = str(activity.get("category", "")).lower()
    tags = activity.get("raw_tags") or {}
    return "museum" in category or "indoor" in category or str(tags.get("tourism", "")).lower() == "museum" or str(tags.get("indoor", "")).lower() == "yes"


def build_weather_proposal(trip, *, day_number: int, now: datetime | None = None) -> dict[str, Any]:
    itinerary = trip.latest_itinerary
    inputs = trip.planning_inputs or {}
    days = itinerary.get("days") if isinstance(itinerary, dict) else None
    if not days:
        raise ValueError("This saved trip has no multi-day itinerary to update.")
    day = next((item for item in days if item.get("day_number") == day_number), None)
    if day is None:
        raise ValueError("The requested itinerary day does not exist.")
    catalog = {item["id"]: item for item in inputs.get("attractions", []) if isinstance(item, dict) and item.get("id")}
    original_stops = day.get("stops", [])
    date_value = str(day.get("date") or trip.start_date)
    slots = [(stop, catalog.get(stop.get("attraction_id"))) for stop in original_stops]
    planned_ids = {stop.get("attraction_id") for saved_day in days for stop in saved_day.get("stops", [])}
    completed = set(trip.completed_attraction_ids or [])
    replace_risk_threshold = float(os.getenv("WEATHER_REPLAN_RISK_THRESHOLD", "0.65"))
    transport_mode = (trip.planning_options or {}).get("transportation_mode", "mixed")
    walking_tolerance = float((trip.preferences or {}).get("walking_tolerance", 0.5))

    def travel_minutes(left, right):
        return estimate_minutes(left, right, transport_mode=transport_mode, walking_tolerance=walking_tolerance)
    possible_alternatives = [item for item in catalog.values()
                             if item.get("id") not in planned_ids and item.get("id") not in completed and _is_indoor(item)]
    weather_targets = [item for _, item in slots if item] + possible_alternatives
    coords = [(float(item["latitude"]), float(item["longitude"])) for item in weather_targets
              if item.get("latitude") is not None and item.get("longitude") is not None]
    forecasts = fetch_forecasts(coords, now=now)
    retrieved_at = now or datetime.now(timezone.utc)
    analyses: dict[str, dict[str, Any]] = {}
    stop_risk: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for stop, activity in slots:
        if not activity:
            warnings.append(f"Forecast unavailable for {stop.get('name', 'an itinerary stop')}: source attraction details are missing.")
            continue
        point = (round(float(activity["latitude"]), 5), round(float(activity["longitude"]), 5))
        forecast = forecasts.get(point)
        slot_weather = forecast_at(forecast, _scheduled(date_value, stop.get("arrival_minute", 540))) if forecast else {"forecast_time": None, "values": {}}
        risk = assess_weather_risk(activity, slot_weather, retrieved_at=(forecast or {}).get("retrieved_at", retrieved_at.isoformat()))
        stop_risk[stop["attraction_id"]] = risk
        analyses[stop["attraction_id"]] = {"attraction_id": stop["attraction_id"], "name": stop.get("name"),
                                             "scheduled_time": slot_weather.get("forecast_time"), "risk": risk}
    revised_stops = [dict(stop) for stop in original_stops]
    for index, stop in enumerate(revised_stops):
        if stop.get("attraction_id") in stop_risk:
            stop["weather_assessment"] = stop_risk[stop["attraction_id"]]
    changes = []
    all_catalog = list(catalog.values())
    # Only replace a forecast-affected, incomplete outdoor activity with a cataloged alternative
    # that has forecast data and can fit the same reserved window. Never fabricate POIs.
    for i, (stop, activity) in enumerate(slots):
        if not activity or stop.get("attraction_id") in completed:
            continue
        risk = stop_risk.get(stop["attraction_id"], {})
        if (risk.get("advisory_score") is None
                or risk["advisory_score"] < replace_risk_threshold
                or not risk.get("outdoor_suitability_assumed")):
            continue
        arrival, departure = int(stop.get("arrival_minute", 540)), int(stop.get("departure_minute", 600))
        duration = departure - arrival
        prior = catalog.get(original_stops[i - 1].get("attraction_id")) if i else None
        following = catalog.get(original_stops[i + 1].get("attraction_id")) if i + 1 < len(original_stops) else None
        if i and revised_stops[i - 1].get("attraction_id") != original_stops[i - 1].get("attraction_id"):
            prior = catalog.get(revised_stops[i - 1].get("attraction_id"), prior)
        prior_stop = revised_stops[i - 1] if i else None
        candidates = []
        for candidate in all_catalog:
            candidate_id = candidate.get("id")
            if candidate_id in planned_ids or candidate_id in completed:
                continue
            if not _is_indoor(candidate):
                continue
            if candidate.get("availability_risk_known") is True and float(candidate.get("availability_risk") or 0) >= replace_risk_threshold:
                continue
            lat, lon = candidate.get("latitude"), candidate.get("longitude")
            if lat is None or lon is None:
                continue
            point = (round(float(lat), 5), round(float(lon), 5))
            forecast = forecasts.get(point)
            if forecast is None:
                # Alternative forecasts are part of same batch; absent means this point was invalid/missing.
                continue
            candidate_weather = forecast_at(forecast, _scheduled(date_value, arrival))
            candidate_risk = assess_weather_risk(candidate, candidate_weather, retrieved_at=forecast["retrieved_at"])
            if not candidate_risk["known"] or (candidate_risk.get("score") or 0) >= replace_risk_threshold:
                continue
            candidate_duration = int(candidate.get("visit_minutes") or duration)
            if candidate_duration > duration:
                continue
            if candidate.get("opening_window_known") is True and (
                arrival < int(candidate.get("opening_minute", 540))
                or arrival + candidate_duration > int(candidate.get("closing_minute", 1020))
            ):
                continue
            left = (float(prior["latitude"]), float(prior["longitude"])) if prior else (trip.start_latitude, trip.start_longitude)
            right = (float(following["latitude"]), float(following["longitude"])) if following else (float(lat), float(lon))
            old_left = (float(activity["latitude"]), float(activity["longitude"]))
            old_right = (float(following["latitude"]), float(following["longitude"])) if following else old_left
            travel_new = travel_minutes(left, (float(lat), float(lon)))
            travel_new += travel_minutes((float(lat), float(lon)), right) if following else 0
            travel_old = travel_minutes(left, old_left)
            travel_old += travel_minutes(old_left, old_right) if following else 0
            extra = max(0, travel_new - travel_old)
            previous_departure = int(prior_stop.get("departure_minute", 540)) if prior_stop else 540
            if arrival - previous_departure < travel_minutes(left, (float(lat), float(lon))):
                continue
            if following and following.get("latitude") is not None and following.get("longitude") is not None:
                next_travel = travel_minutes((float(lat), float(lon)), (float(following["latitude"]), float(following["longitude"])))
                if int(original_stops[i + 1].get("arrival_minute", departure)) - departure < next_travel:
                    continue
            if departure + extra > trip.available_minutes_per_day:
                continue
            old_cost, new_cost = float(stop.get("cost", 0)), float(candidate.get("cost", 0))
            budget_estimate = itinerary.get("budget_estimate") or {}
            estimated_total = float(budget_estimate.get("total_estimated", itinerary.get("total_cost", 0)))
            budget_limit = float(budget_estimate.get("budget_limit", trip.budget))
            if estimated_total - old_cost + new_cost > budget_limit:
                continue
            candidates.append((extra, candidate_risk["score"], -float(candidate.get("preference_score", 0)), candidate, candidate_risk))
        candidates.sort(key=lambda entry: entry[:3])
        if candidates:
            extra, _, _, replacement, replacement_risk = candidates[0]
            planned_ids.add(replacement["id"])
            revised_stops[i] = {**stop, "attraction_id": replacement["id"], "name": replacement["name"],
                                "cost": replacement.get("cost", 0), "weather_assessment": replacement_risk}
            changes.append({"status": "replaced", "original": stop, "revised": revised_stops[i],
                            "reason": "Forecast indicates elevated weather risk for this outdoor activity; a cataloged indoor alternative has a lower forecast risk.",
                            "weather_risk": risk, "alternative_weather_risk": replacement_risk,
                            "additional_travel_minutes": extra,
                            "additional_cost": float(revised_stops[i].get("cost", 0)) - float(stop.get("cost", 0))})
            if replacement.get("cost_known") is False:
                warnings.append(f"The entrance fee for {replacement['name']} is unknown; its numeric budget value is an optimizer placeholder.")
            if replacement.get("opening_window_known") is False:
                warnings.append(f"Opening hours for {replacement['name']} are unknown; confirm the venue is open at the proposed time.")
            if replacement.get("availability_risk_known") is not True:
                warnings.append(f"Availability for {replacement['name']} has not been verified by a live venue source.")
        else:
            warnings.append(f"{stop.get('name')} has elevated forecast weather risk; no suitable forecast-checked alternative fits its reserved time and budget, so it remains in the proposal.")
            changes.append({"status": "unchanged", "original": stop, "revised": stop,
                            "reason": "Elevated weather risk; no verified suitable alternative fits the existing schedule.",
                            "weather_risk": risk, "additional_travel_minutes": 0, "additional_cost": 0})
    old_travel_minutes = sum(int(stop.get("travel_minutes_before", 0)) for stop in original_stops)
    if any(change.get("status") == "replaced" for change in changes):
        previous_location = (trip.start_latitude, trip.start_longitude)
        revised_travel_minutes = 0
        for stop in revised_stops:
            activity = catalog.get(stop.get("attraction_id"))
            if activity and activity.get("latitude") is not None and activity.get("longitude") is not None:
                location = (float(activity["latitude"]), float(activity["longitude"]))
                leg = travel_minutes(previous_location, location)
                stop["travel_minutes_before"] = leg
                revised_travel_minutes += leg
                previous_location = location
    else:
        revised_travel_minutes = old_travel_minutes
    travel_delta = revised_travel_minutes - old_travel_minutes
    if changes:
        for change in changes:
            change["additional_travel_minutes"] = 0
        changes[0]["additional_travel_minutes"] = travel_delta
    revised_day = {**day, "stops": revised_stops, "total_travel_minutes": revised_travel_minutes}
    revised_day["total_cost"] = round(sum(float(stop.get("cost", 0)) for stop in revised_stops), 2)
    revised_day["total_visit_minutes"] = sum(int(stop.get("departure_minute", 0)) - int(stop.get("arrival_minute", 0)) for stop in revised_stops)
    revised_itinerary = {**itinerary, "days": [revised_day if item.get("day_number") == day_number else item for item in days]}
    old_day_cost = float(day.get("total_cost", sum(float(s.get("cost", 0)) for s in original_stops)))
    revised_itinerary["total_cost"] = round(float(itinerary.get("total_cost", 0)) - old_day_cost + revised_day["total_cost"], 2)
    revised_itinerary["total_travel_minutes"] = int(itinerary.get("total_travel_minutes", 0)) + travel_delta
    additional_cost = round(sum(float(c.get("additional_cost", 0)) for c in changes), 2)
    all_available = bool(analyses) and all(
        item["risk"]["known"] and item["risk"]["confidence"] != "partial"
        for item in analyses.values()
    )
    budget_estimate = revised_itinerary.get("budget_estimate")
    if isinstance(budget_estimate, dict):
        budget_estimate = dict(budget_estimate)
        budget_estimate["total_estimated"] = round(float(budget_estimate.get("total_estimated", 0)) + additional_cost, 2)
        budget_estimate["remaining_budget"] = round(float(budget_estimate.get("budget_limit", trip.budget)) - budget_estimate["total_estimated"], 2)
        budget_estimate["within_budget"] = budget_estimate["remaining_budget"] >= 0
        for category in budget_estimate.get("categories", []):
            if category.get("key") == "attractions":
                category["amount"] = round(float(category.get("amount", 0)) + additional_cost, 2)
        revised_itinerary["budget_estimate"] = budget_estimate
        within_budget = budget_estimate["within_budget"]
    else:
        within_budget = revised_itinerary["total_cost"] <= trip.budget
    proposal_warnings = warnings + ([] if all_available else ["Forecast coverage is partial or unavailable; unknown weather fields were not treated as zero risk."])
    if not within_budget:
        budget_warning = "The revised itinerary exceeds the existing full-trip budget estimate; review the cost assumptions before accepting."
        revised_itinerary["feasible"] = False
        revised_itinerary["warnings"] = list(dict.fromkeys([*revised_itinerary.get("warnings", []), budget_warning]))
        proposal_warnings.append(budget_warning)
    return {
        "proposal_id": str(uuid4()), "base_revision": trip.itinerary_revision, "mode": "forecast",
        "day_number": day_number, "date": date_value, "provider": PROVIDER,
        "retrieved_at": retrieved_at.isoformat(), "attribution": ATTRIBUTION,
        "forecast_available": bool(analyses) and any(item["risk"]["variables"] for item in analyses.values()),
        "can_accept": bool(analyses) and any(item["risk"]["variables"] for item in analyses.values()),
        "original_stops": original_stops, "revised_stops": revised_stops,
        "weather_summary": list(analyses.values()), "changes": changes, "revised_itinerary": revised_itinerary,
        "additional_travel_minutes": travel_delta,
        "additional_cost": additional_cost,
        "within_budget": within_budget,
        "warnings": list(dict.fromkeys(proposal_warnings)),
    }
