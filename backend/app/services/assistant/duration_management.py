"""Planner-backed duration changes staged for the assistant proposal workflow."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
import os
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Attraction, Trip
from app.schemas import (
    AttractionInput, ConfirmedActivity, MultiDayOptimizeRequest, Preferences,
)
from app.services.budget import attraction_budget_after_fixed_costs, estimate_trip_budget
from app.services.multiday import generate_multiday_greedy
from app.services.planner import risk_data_status
from app.services.poi_catalog import to_optimizer_attraction
from app.services.assistant.schemas import AssistantIntentOutput


class TripDurationChangeError(ValueError):
    """A user-facing reason the requested duration cannot be proposed safely."""


@dataclass
class PreparedDurationChange:
    start_date: date
    end_date: date
    request: MultiDayOptimizeRequest
    staged_trip: SimpleNamespace
    result: dict
    changes: list[dict]
    summary: str


def _stop_value(stop, key: str, default=None):
    return stop.get(key, default) if isinstance(stop, dict) else getattr(stop, key, default)


def _day_value(day, key: str, default=None):
    return day.get(key, default) if isinstance(day, dict) else getattr(day, key, default)


def _trip_snapshot(
    trip: Trip,
    *,
    end_date: date,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=trip.id,
        name=trip.name,
        origin=trip.origin,
        destination=trip.destination,
        start_date=trip.start_date,
        end_date=end_date,
        budget=trip.budget,
        available_minutes_per_day=trip.available_minutes_per_day,
        start_latitude=trip.start_latitude,
        start_longitude=trip.start_longitude,
        preferences=deepcopy(trip.preferences or {}),
        planning_options=deepcopy(trip.planning_options or {}),
        accommodation_selection=trip.accommodation_selection,
    )


def _validate_saved_days(trip: Trip, duration_days: int) -> tuple[list[dict], set[str]]:
    days = (trip.latest_itinerary or {}).get("days") or []
    current_days = (trip.end_date - trip.start_date).days + 1
    if len(days) != current_days:
        raise TripDurationChangeError(
            "The saved itinerary day count does not match the trip dates. Regenerate the itinerary before changing its duration."
        )
    completed = {str(value) for value in (trip.completed_attraction_ids or [])}
    seen = set()
    for index, day in enumerate(days, start=1):
        if day.get("day_number") != index:
            raise TripDurationChangeError("The saved itinerary day numbering is inconsistent; no duration proposal was created.")
        day_date = day.get("date")
        if isinstance(day_date, str):
            try:
                day_date = date.fromisoformat(day_date)
            except ValueError as exc:
                raise TripDurationChangeError("A saved itinerary date is invalid; no duration proposal was created.") from exc
        if day_date != trip.start_date + timedelta(days=index - 1):
            raise TripDurationChangeError("The saved itinerary dates are inconsistent; no duration proposal was created.")
        for stop in day.get("stops") or []:
            attraction_id = str(stop.get("attraction_id", ""))
            if not attraction_id or attraction_id in seen:
                raise TripDurationChangeError("The saved itinerary contains a missing or duplicate attraction; no duration proposal was created.")
            seen.add(attraction_id)
    missing_completed = completed - seen
    if missing_completed:
        raise TripDurationChangeError("A completed activity is missing from the saved itinerary, so GoWander cannot safely change its duration.")
    if any(
        day.get("day_number", 0) > duration_days
        and any(str(stop.get("attraction_id")) in completed for stop in day.get("stops") or [])
        for day in days
    ):
        raise TripDurationChangeError(
            "This shorter duration would remove a completed activity. Choose a duration that includes its day; completed activities are protected."
        )
    return days, completed


def _all_catalog_candidates(db: Session, trip: Trip, request: MultiDayOptimizeRequest) -> list[AttractionInput]:
    by_id = {item.id: item for item in request.attractions}
    records = db.scalars(
        select(Attraction)
        .where(func.lower(Attraction.destination) == trip.destination.strip().lower())
        .order_by(Attraction.name, Attraction.id)
    ).all()
    for row in records:
        try:
            candidate = AttractionInput.model_validate(to_optimizer_attraction(row))
        except Exception:
            continue
        # Keep the saved optimizer projection for known trip inputs. Catalog rows
        # only extend the candidate pool; they never replace scheduled records.
        by_id.setdefault(candidate.id, candidate)
    return list(by_id.values())


def _scheduled_attractions(
    days: list[dict], by_id: dict[str, AttractionInput],
) -> list[AttractionInput]:
    ids = [
        str(stop.get("attraction_id"))
        for day in days for stop in (day.get("stops") or [])
    ]
    missing = sorted(set(ids) - by_id.keys())
    if missing:
        raise TripDurationChangeError(
            "The saved planner data is missing a scheduled attraction, so the duration change cannot be planned safely."
        )
    return [by_id[item] for item in dict.fromkeys(ids)]


def _combined_extension_result(
    *,
    trip: Trip,
    staged_trip: SimpleNamespace,
    request: MultiDayOptimizeRequest,
    original_days: list[dict],
    new_days: list[dict],
    all_attractions: list[AttractionInput],
    new_plan_result: dict,
) -> dict:
    day_offset = len(original_days)
    normalized_new_days = []
    for day in new_days:
        item = deepcopy(day)
        item["day_number"] += day_offset
        normalized_new_days.append(item)
    days = [deepcopy(day) for day in original_days] + normalized_new_days
    estimates = estimate_trip_budget(
        trip=staged_trip,
        days=days,
        attractions=all_attractions,
        data_source=request.data_source,
    )
    stops = [stop for day in days for stop in day.get("stops", [])]
    preferences_by_id = {item.id: item for item in all_attractions}
    attraction_values = [
        preferences_by_id[str(_stop_value(stop, "attraction_id"))]
        for stop in stops if str(_stop_value(stop, "attraction_id")) in preferences_by_id
    ]
    risk_scores = [_stop_value(stop, "risk_score") for stop in stops]
    risk_complete = all(value is not None for value in risk_scores)
    survival = 1.0
    for value in risk_scores:
        if value is not None:
            survival *= 1.0 - float(value)
    warnings = list(dict.fromkeys(
        [*(trip.latest_itinerary or {}).get("warnings", []), *new_plan_result.get("warnings", [])]
    ))
    if not estimates["within_budget"]:
        warnings.append(
            f"Estimated full-trip costs exceed the budget by ₹{abs(estimates['remaining_budget']):,.0f}; review the estimate or adjust the trip budget."
        )
    scheduled_ids = {str(_stop_value(stop, "attraction_id")) for stop in stops}
    unknown_fees = [item for item in all_attractions if item.id in scheduled_ids and item.cost_known is False]
    unknown_hours = [item for item in all_attractions if item.id in scheduled_ids and item.opening_window_known is False]
    unknown_durations = [item for item in all_attractions if item.id in scheduled_ids and item.visit_duration_known is False]
    if unknown_fees:
        warnings.append(f"Entrance fees are unknown for {len(unknown_fees)} scheduled attraction(s); unknown fees are not verified as free.")
    if unknown_hours:
        warnings.append(f"Opening hours are unknown for {len(unknown_hours)} scheduled attraction(s); the planner used an assumed time window.")
    if unknown_durations:
        warnings.append(f"Visit duration is unknown for {len(unknown_durations)} scheduled attraction(s); category-based planning estimates were used.")
    feasible = bool(new_plan_result.get("feasible")) and estimates["within_budget"]
    for day in normalized_new_days:
        day["warnings"] = list(dict.fromkeys(day.get("warnings", [])))
    return {
        "days": days,
        "total_cost": round(sum(float(_day_value(day, "total_cost", 0) or 0) for day in days), 2),
        "total_travel_minutes": sum(int(_day_value(day, "total_travel_minutes", 0) or 0) for day in days),
        "total_visit_minutes": sum(int(_day_value(day, "total_visit_minutes", 0) or 0) for day in days),
        "satisfaction": round(
            sum(float(_stop_value(stop, "preference_score", 0) or 0) for stop in stops) / len(stops), 3
        ) if stops else 0.0,
        "risk_score": round(1 - survival, 3) if stops and risk_complete else None,
        "risk_data_status": risk_data_status(attraction_values),
        "feasible": feasible,
        "warnings": list(dict.fromkeys(warnings)),
        "budget_estimate": estimates,
    }


def prepare_duration_change(
    *,
    db: Session,
    trip: Trip,
    request: MultiDayOptimizeRequest,
    intent: AssistantIntentOutput,
) -> PreparedDurationChange:
    parameters = intent.parameters
    requested_days = parameters["duration_days"]
    current_days = (trip.end_date - trip.start_date).days + 1
    actual_direction = "extend" if requested_days > current_days else "shorten"
    if requested_days == current_days:
        raise TripDurationChangeError(f"This trip is already {current_days} days long. No changes were made.")
    if parameters["direction"] != actual_direction:
        raise TripDurationChangeError(
            f"The saved trip is {current_days} days long, so {requested_days} days would {actual_direction} it. Please confirm the duration you want."
        )
    try:
        requested_end = trip.start_date + timedelta(days=requested_days - 1)
    except OverflowError as exc:
        raise TripDurationChangeError("Those dates exceed the supported calendar range.") from exc

    original_days, _completed_ids = _validate_saved_days(trip, requested_days)
    staged_trip = _trip_snapshot(trip, end_date=requested_end)
    by_id = {item.id: item for item in request.attractions}

    if requested_days < current_days:
        scheduled = _scheduled_attractions(original_days, by_id)
        confirmed = []
        for day in original_days[:requested_days]:
            for stop in day.get("stops") or []:
                arrival = stop.get("arrival_minute")
                if not isinstance(arrival, int) or isinstance(arrival, bool):
                    raise TripDurationChangeError("A retained activity has no reliable scheduled start time.")
                confirmed.append(ConfirmedActivity(
                    attraction_id=str(stop["attraction_id"]),
                    day_number=int(day["day_number"]),
                    start_minute=arrival,
                ))
        planner_request = request.model_copy(update={
            "attractions": scheduled,
            "confirmed_activities": confirmed,
        })
        from app.api.trips import _build_saved_multiday_plan

        result = _build_saved_multiday_plan(staged_trip, planner_request)
        request = planner_request
        changes = [{
            "field": "trip_duration", "before": current_days, "after": requested_days,
            "days_removed": list(range(requested_days + 1, current_days + 1)),
        }]
        summary = f"Shorten your {trip.destination} trip from {current_days} days to {requested_days} days"
    else:
        existing_ids = {
            str(stop.get("attraction_id"))
            for day in original_days for stop in (day.get("stops") or [])
        }
        all_attractions = _all_catalog_candidates(db, trip, request)
        additions = [item for item in all_attractions if item.id not in existing_ids]
        additional_days = requested_days - current_days
        if not additions:
            raise TripDurationChangeError(
                "There are no unscheduled attractions in the saved planning data or destination catalog to plan on the added day(s). Your trip was not changed."
            )

        full_budget = attraction_budget_after_fixed_costs(staged_trip)
        existing_attraction_cost = sum(float(_day_value(day, "total_cost", 0) or 0) for day in original_days)
        new_day_budget = max(0.0, full_budget - existing_attraction_cost)
        segment_start = trip.end_date + timedelta(days=1)
        segment_end = requested_end
        options = trip.planning_options or {}
        preferences = Preferences.model_validate(trip.preferences or {})
        result = generate_multiday_greedy(
            attractions=additions,
            preferences=preferences,
            start_date=segment_start,
            end_date=segment_end,
            start_latitude=trip.start_latitude,
            start_longitude=trip.start_longitude,
            budget=new_day_budget,
            available_minutes_per_day=trip.available_minutes_per_day,
            meal_breaks=request.meal_breaks,
            confirmed_activities=[],
            routing_provider=os.getenv("ROUTING_PROVIDER", "haversine"),
            transport_mode=options.get("transportation_mode", "mixed"),
            walking_tolerance=preferences.walking_tolerance,
        )
        generated_days = result.get("days", [])
        if len(generated_days) != additional_days or any(not day.get("stops") for day in generated_days):
            raise TripDurationChangeError(
                "The existing planner could not produce activities for every added day from the saved catalog. Try a shorter extension; no trip changes were made."
            )
        if not result.get("feasible"):
            raise TripDurationChangeError(
                "The planner could not fit a valid schedule on the added day(s) within the current time and budget constraints. No changes were made."
            )
        combined = _combined_extension_result(
            trip=trip,
            staged_trip=staged_trip,
            request=request,
            original_days=original_days,
            new_days=generated_days,
            all_attractions=all_attractions,
            new_plan_result=result,
        )
        if not combined["feasible"]:
            raise TripDurationChangeError(
                "The extended itinerary would exceed current planning constraints or the trip budget. Your saved trip remains unchanged."
            )
        used_new_ids = {
            str(_stop_value(stop, "attraction_id"))
            for day in generated_days for stop in day.get("stops", [])
        }
        persisted_attractions = list(request.attractions)
        persisted_ids = {item.id for item in persisted_attractions}
        persisted_attractions.extend(
            item for item in additions if item.id in used_new_ids and item.id not in persisted_ids
        )
        request = request.model_copy(update={"attractions": persisted_attractions})
        result = combined
        changes = [{
            "field": "trip_duration", "before": current_days, "after": requested_days,
            "days_added": list(range(current_days + 1, requested_days + 1)),
        }]
        summary = f"Extend your {trip.destination} trip from {current_days} days to {requested_days} days"

    additional_context = parameters.get("additional_context", "").strip()
    if additional_context:
        changes.append({
            "field": "duration_context",
            "before": "Not specified",
            "after": additional_context,
        })
    return PreparedDurationChange(
        start_date=trip.start_date,
        end_date=requested_end,
        request=request,
        staged_trip=staged_trip,
        result=result,
        changes=changes,
        summary=summary,
    )
