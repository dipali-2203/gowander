from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.models import AssistantTripProposal, Trip
from app.schemas import (
    ConfirmedActivity, MultiDayItineraryResponse, MultiDayOptimizeRequest,
    Preferences, TripPlanningOptions,
)
from app.services.assistant.attraction_management import (
    AttractionChangeError, PreparedAttractionChange, prepare_attraction_change,
)
from app.services.assistant.schemas import AssistantIntentOutput


PACE_VALUES = {"relaxed": 0.25, "balanced": 0.5, "fast": 0.8}
PROPOSAL_TTL = timedelta(days=7)


def _trip_snapshot(trip: Trip, *, budget: float, preferences: dict, planning_options: dict) -> SimpleNamespace:
    """Planning/budget adapter. It never mutates the ORM trip instance."""
    return SimpleNamespace(
        id=trip.id,
        name=trip.name,
        origin=trip.origin,
        destination=trip.destination,
        start_date=trip.start_date,
        end_date=trip.end_date,
        budget=budget,
        available_minutes_per_day=trip.available_minutes_per_day,
        start_latitude=trip.start_latitude,
        start_longitude=trip.start_longitude,
        preferences=preferences,
        planning_options=deepcopy(planning_options),
        accommodation_selection=trip.accommodation_selection,
    )


def _current_completed_reservations(trip: Trip, request: MultiDayOptimizeRequest) -> tuple[list[ConfirmedActivity], list[str]]:
    completed_ids = {str(value) for value in (trip.completed_attraction_ids or [])}
    if not completed_ids:
        return list(request.confirmed_activities), []

    completed_locations: dict[str, tuple[int, int]] = {}
    for day in ((trip.latest_itinerary or {}).get("days") or []):
        day_number = day.get("day_number")
        for stop in day.get("stops") or []:
            attraction_id = str(stop.get("attraction_id", ""))
            if attraction_id in completed_ids and isinstance(day_number, int):
                start_minute = stop.get("arrival_minute")
                if isinstance(start_minute, int) and not isinstance(start_minute, bool):
                    completed_locations[attraction_id] = (day_number, start_minute)

    missing = sorted(completed_ids - completed_locations.keys())
    if missing:
        return [], [
            "A completed activity is missing a reliable day or start time, so GoWander could not safely build a proposal."
        ]

    reservations = [item for item in request.confirmed_activities if item.attraction_id not in completed_ids]
    reservations.extend(
        ConfirmedActivity(attraction_id=attraction_id, day_number=day, start_minute=start)
        for attraction_id, (day, start) in sorted(completed_locations.items())
    )
    return reservations, []


def _itinerary_comparison(original: dict, proposed: dict) -> dict:
    def index(itinerary: dict) -> dict[str, dict]:
        result = {}
        for day in itinerary.get("days", []):
            for stop in day.get("stops", []):
                attraction_id = str(stop.get("attraction_id", ""))
                if attraction_id:
                    result[attraction_id] = {
                        "attraction_id": attraction_id,
                        "name": stop.get("name", "Attraction"),
                        "day_number": day.get("day_number"),
                        "arrival_minute": stop.get("arrival_minute"),
                    }
        return result

    before, after = index(original), index(proposed)
    retained, moved, added, removed = [], [], [], []
    for attraction_id in sorted(before.keys() | after.keys()):
        old, new = before.get(attraction_id), after.get(attraction_id)
        if old is None:
            added.append(new)
        elif new is None:
            removed.append(old)
        elif (old["day_number"], old["arrival_minute"]) != (new["day_number"], new["arrival_minute"]):
            moved.append({"before": old, "after": new})
        else:
            retained.append({"before": old, "after": new})
    return {"added_stops": added, "removed_stops": removed, "moved_stops": moved, "retained_stops": retained}


def _budget_comparison(original: dict | None, proposed: dict | None) -> dict:
    before = deepcopy(original) if isinstance(original, dict) else None
    after = deepcopy(proposed) if isinstance(proposed, dict) else None
    before_total = before.get("total_estimated") if before else None
    after_total = after.get("total_estimated") if after else None
    difference = None
    if isinstance(before_total, (int, float)) and isinstance(after_total, (int, float)):
        difference = round(float(after_total) - float(before_total), 2)
    return {
        "currency": "INR",
        "before": before,
        "after": after,
        "estimated_difference": difference,
        "difference_status": "estimated" if difference is not None else "unavailable",
    }


def _planned_location(result: dict, attraction_id: str) -> tuple[int, int] | None:
    for day in result.get("days", []):
        for stop in day.get("stops", []):
            stop_id = stop.get("attraction_id") if isinstance(stop, dict) else stop.attraction_id
            if str(stop_id) == attraction_id:
                arrival = stop.get("arrival_minute") if isinstance(stop, dict) else stop.arrival_minute
                return int(day["day_number"]), int(arrival)
    return None


def _completed_locations_preserved(trip: Trip, result: dict) -> bool:
    original = {
        str(stop.get("attraction_id")): (day.get("day_number"), stop.get("arrival_minute"))
        for day in ((trip.latest_itinerary or {}).get("days") or [])
        for stop in day.get("stops", [])
    }
    return all(
        _planned_location(result, str(item)) == original.get(str(item))
        for item in (trip.completed_attraction_ids or [])
    )


def _candidate_request(request: MultiDayOptimizeRequest, candidate) -> MultiDayOptimizeRequest:
    attractions = [item for item in request.attractions if item.id != candidate.id]
    attractions.append(candidate)
    return request.model_copy(update={"attractions": attractions})


def _find_plan_with_attraction(
    *, trip: Trip, staged_trip, request: MultiDayOptimizeRequest,
    candidate, required_day: int | None,
) -> tuple[MultiDayOptimizeRequest, dict] | None:
    from app.api.trips import _build_saved_multiday_plan

    candidate_request = _candidate_request(request, candidate)
    plan = _build_saved_multiday_plan(staged_trip, candidate_request)
    location = _planned_location(plan, candidate.id)
    if (
        plan.get("feasible") and location is not None
        and (required_day is None or location[0] == required_day)
        and _completed_locations_preserved(trip, plan)
    ):
        return candidate_request, plan

    day_count = (trip.end_date - trip.start_date).days + 1
    days = [required_day] if required_day is not None else list(range(1, min(day_count, 14) + 1))
    day_start = 540 if trip.available_minutes_per_day >= 540 else 0
    first_minute = max(day_start, candidate.opening_minute)
    last_minute = min(trip.available_minutes_per_day, candidate.closing_minute) - candidate.visit_minutes
    if last_minute < first_minute:
        return None
    slots = list(dict.fromkeys((first_minute, min(first_minute + 60, last_minute), last_minute)))
    for day_number in days:
        for start_minute in slots:
            confirmed = [
                item for item in candidate_request.confirmed_activities
                if item.attraction_id != candidate.id
            ]
            confirmed.append(ConfirmedActivity(
                attraction_id=candidate.id, day_number=day_number, start_minute=start_minute,
            ))
            forced_request = candidate_request.model_copy(update={"confirmed_activities": confirmed})
            plan = _build_saved_multiday_plan(staged_trip, forced_request)
            location = _planned_location(plan, candidate.id)
            if (
                plan.get("feasible") and location == (day_number, start_minute)
                and _completed_locations_preserved(trip, plan)
            ):
                return forced_request, plan
    return None


def _attraction_change(
    prepared: PreparedAttractionChange, selected: list, result: dict,
) -> tuple[list[dict], str]:
    if prepared.operation == "remove":
        target = prepared.target
        return ([{
            "field": "attraction_removed", "before": target.name, "after": "Removed",
            "attraction_id": target.id, "day_number": prepared.target_day,
            "category": target.catalog_category or target.category,
            "cost_known": target.cost_known is True,
            "fee": target.cost if target.cost_known is True else None,
            "opening_hours": target.opening_hours,
            "visit_duration_known": target.visit_duration_known is True,
            "visit_minutes": target.visit_minutes if target.visit_duration_known is True else None,
            "source_url": target.source_url,
            "provider_name": target.provider_name,
            "attribution": target.attribution,
            "license_name": target.license_name,
            "data_source": target.data_source,
        }], f"Remove {target.name} from Day {prepared.target_day}")

    records = []
    for candidate in selected:
        location = _planned_location(result, candidate.id)
        day_number = location[0] if location else prepared.requested_day
        field = "attraction_replaced" if prepared.operation == "replace" else "attraction_added"
        before = prepared.target.name if prepared.operation == "replace" else "Not in itinerary"
        records.append({
            "field": field, "before": before, "after": candidate.name,
            "attraction_id": candidate.id, "day_number": day_number,
            "category": candidate.catalog_category or candidate.category,
            "cost_known": candidate.cost_known is True,
            "fee": candidate.cost if candidate.cost_known is True else None,
            "opening_hours": candidate.opening_hours,
            "visit_duration_known": candidate.visit_duration_known is True,
            "visit_minutes": candidate.visit_minutes if candidate.visit_duration_known is True else None,
            "source_url": candidate.source_url,
            "provider_name": candidate.provider_name,
            "attribution": candidate.attribution,
            "license_name": candidate.license_name,
            "data_source": candidate.data_source,
        })
    if prepared.operation == "replace":
        summary = f"Replace {prepared.target.name} with {', '.join(item.name for item in selected)}"
    else:
        summary = f"Add {', '.join(item.name for item in selected)}"
    return records, f"{summary} to your itinerary"


def create_trip_proposal(
    *,
    db,
    user_id: int,
    trip: Trip,
    intent: AssistantIntentOutput,
    request_id: str | None = None,
) -> tuple[dict | None, str]:
    if not trip.planning_inputs:
        return None, "This saved trip does not have the attraction and planning inputs needed to safely recalculate an itinerary. Generate a saved itinerary in the planner first."
    if not trip.latest_itinerary:
        return None, "This trip does not have a saved itinerary to compare yet. Generate one in the planner first."

    try:
        original_request = MultiDayOptimizeRequest.model_validate(trip.planning_inputs)
    except Exception:
        return None, "The saved planning inputs are incomplete, so I could not safely create a proposal. Please regenerate the itinerary from the planner first."

    attraction_change = None
    if intent.action == "change_attractions":
        try:
            attraction_change = prepare_attraction_change(db, trip, original_request, intent)
        except AttractionChangeError as exc:
            return None, str(exc)
        original_request = attraction_change.request

    proposed_budget = float(trip.budget)
    proposed_preferences = deepcopy(trip.preferences or {})
    proposed_planning_options = deepcopy(trip.planning_options or {})
    if intent.action == "change_travel_pace":
        if _pace_label(trip.preferences).casefold() == intent.parameters["pace"]:
            return None, f"Your saved trip is already set to a {intent.parameters['pace']} pace. No changes were made."
        proposed_preferences["travel_pace"] = PACE_VALUES[intent.parameters["pace"]]
        proposal_type = "travel_pace_change"
        display_value = intent.parameters["pace"].capitalize()
        changes = [{"field": "travel_pace", "before": _pace_label(trip.preferences), "after": display_value}]
        summary = f"Make your {trip.destination} itinerary more {intent.parameters['pace']}"
    elif intent.action == "change_budget":
        amount = float(intent.parameters["amount_inr"])
        adjustment = intent.parameters["adjustment"]
        if adjustment == "increase_by":
            proposed_budget += amount
        elif adjustment == "decrease_by":
            proposed_budget -= amount
        else:
            proposed_budget = amount
        if not 1 <= proposed_budget <= 5_000_000:
            return None, "That budget would fall outside the supported range of ₹1 to ₹5,000,000. What budget would you like to use?"
        if proposed_budget == float(trip.budget):
            return None, "That is already the saved trip budget. No changes were made."
        proposal_type = "budget_change"
        changes = [{"field": "budget_inr", "before": trip.budget, "after": proposed_budget}]
        summary = f"Update the budget for your {trip.destination} trip to ₹{proposed_budget:,.0f}"
    elif intent.action == "change_preferences":
        parameters = intent.parameters
        changes = []
        if "interests" in parameters:
            current_interests = deepcopy(proposed_preferences.get("interests") or {})
            for key, value in sorted(parameters["interests"].items()):
                before = current_interests.get(key)
                if before is not None and float(before) == float(value):
                    continue
                current_interests[key] = float(value)
                changes.append({
                    "field": f"interest_{key}",
                    "before": float(before) if before is not None else "Not set",
                    "after": float(value),
                })
            proposed_preferences["interests"] = current_interests
        for key in ("walking_tolerance", "crowd_tolerance", "risk_tolerance"):
            if key not in parameters:
                continue
            before = float(proposed_preferences.get(key, Preferences().model_dump()[key]))
            after = float(parameters[key])
            if before == after:
                continue
            proposed_preferences[key] = after
            changes.append({"field": key, "before": before, "after": after})
        if "transportation_mode" in parameters:
            before = proposed_planning_options.get("transportation_mode", "mixed")
            after = parameters["transportation_mode"]
            if before != after:
                proposed_planning_options["transportation_mode"] = after
                changes.append({"field": "transportation_mode", "before": str(before), "after": str(after)})
        if not changes:
            return None, "Those preferences already match your saved trip. No changes were made."
        try:
            proposed_preferences = Preferences.model_validate(proposed_preferences).model_dump(mode="json")
            proposed_planning_options = TripPlanningOptions.model_validate(proposed_planning_options).model_dump(mode="json")
        except Exception:
            return None, "I could not validate those preference values against the current planner. Your saved trip remains unchanged."
        proposal_type = "preference_change"
        summary = f"Update preferences for your {trip.destination} trip"
    elif intent.action == "change_attractions":
        proposal_type = "attraction_change"
        changes = []
        summary = f"Update attractions for your {trip.destination} trip"
    else:
        return None, "Changing trip duration is not supported yet. Shortening a trip can strand completed activities, and the current planner does not safely preserve them across changed trip dates. Your saved trip remains unchanged."

    confirmed, preservation_errors = _current_completed_reservations(trip, original_request)
    if preservation_errors:
        return None, preservation_errors[0]
    request_data = original_request.model_dump(mode="python")
    request_data["confirmed_activities"] = [item.model_dump(mode="python") for item in confirmed]
    proposed_request = MultiDayOptimizeRequest.model_validate(request_data)
    staged_trip = _trip_snapshot(
        trip, budget=proposed_budget, preferences=proposed_preferences,
        planning_options=proposed_planning_options,
    )
    planner_request = proposed_request
    if attraction_change is not None:
        planner_request = attraction_change.planning_request.model_copy(update={
            "confirmed_activities": proposed_request.confirmed_activities,
        })

    # The saved-trip planner calculates the same deterministic result used by the
    # regenerate endpoint, but this call performs no ORM writes or commits.
    from app.api.trips import _build_saved_multiday_plan

    selected_attractions = []
    try:
        if attraction_change is not None and attraction_change.candidate_groups:
            working_request = planner_request
            result = None
            for group in attraction_change.candidate_groups:
                selected = None
                for candidate in group:
                    if candidate.id in {item.id for item in selected_attractions}:
                        continue
                    planned = _find_plan_with_attraction(
                        trip=trip, staged_trip=staged_trip, request=working_request,
                        candidate=candidate, required_day=attraction_change.requested_day,
                    )
                    if planned is not None:
                        working_request, result = planned
                        selected = candidate
                        selected_attractions.append(candidate)
                        proposed_request = _candidate_request(proposed_request, candidate)
                        break
                if selected is None:
                    subject = attraction_change.target.name if attraction_change.target else "the requested attraction"
                    return None, (
                        f"I couldn't place {subject} within the saved itinerary's time, budget, and completed-activity constraints. "
                        "Your trip remains unchanged."
                    )
            proposed_request = proposed_request.model_copy(update={
                "confirmed_activities": working_request.confirmed_activities,
            })
            changes, summary = _attraction_change(attraction_change, selected_attractions, result)
        else:
            result = _build_saved_multiday_plan(staged_trip, planner_request)
            if attraction_change is not None:
                changes, summary = _attraction_change(attraction_change, [], result)
        proposed_itinerary = MultiDayItineraryResponse(
            trip_id=trip.id,
            algorithm="greedy_multiday",
            data_source=proposed_request.data_source,
            **result,
        ).model_dump(mode="json")
    except (ValueError, RuntimeError) as exc:
        # Do not log provider messages that may include external request details.
        return None, f"I could not build a valid itinerary proposal with the current planning inputs ({type(exc).__name__}). Your trip remains unchanged."

    original_itinerary = deepcopy(trip.latest_itinerary)
    comparison = _itinerary_comparison(original_itinerary, proposed_itinerary)
    completed_ids = {str(value) for value in (trip.completed_attraction_ids or [])}
    proposed_locations = {
        str(stop.get("attraction_id")): (day.get("day_number"), stop.get("arrival_minute"))
        for day in proposed_itinerary.get("days", [])
        for stop in day.get("stops", [])
    }
    original_locations = {
        str(stop.get("attraction_id")): (day.get("day_number"), stop.get("arrival_minute"))
        for day in original_itinerary.get("days", [])
        for stop in day.get("stops", [])
    }
    completed_preserved = all(
        proposed_locations.get(item) == original_locations.get(item) for item in completed_ids
    )
    warnings = list(dict.fromkeys(result.get("warnings", [])))
    if not completed_preserved:
        warnings.append("A completed activity could not be retained on its original day and time; this proposal cannot be accepted safely.")
    if proposed_itinerary.get("budget_estimate", {}).get("unknown_attraction_fee_count", 0):
        warnings.append("Some scheduled attraction fees are unknown. The estimate is partial; unknown fees are not verified as free.")
    valid = bool(result.get("feasible")) and completed_preserved

    original_inputs = {
        "budget": trip.budget,
        "preferences": deepcopy(trip.preferences or {}),
        "planning_inputs": deepcopy(trip.planning_inputs),
    }
    if request_id is not None:
        original_inputs["_assistant_request_id"] = request_id
    proposed_inputs = {
        "budget": proposed_budget,
        "preferences": proposed_preferences,
        "planning_options": proposed_planning_options,
        "planning_inputs": proposed_request.model_dump(mode="json"),
    }
    payload = {
        "proposal_id": str(uuid4()),
        "type": proposal_type,
        "status": "pending",
        "base_revision": trip.itinerary_revision,
        "summary": summary,
        "changes": changes,
        "itinerary_comparison": comparison,
        "budget_comparison": _budget_comparison(
            original_itinerary.get("budget_estimate"), proposed_itinerary.get("budget_estimate"),
        ),
        "validation": {"valid": valid, "issues": [] if valid else ["The proposed schedule does not satisfy all current planning constraints."]},
        "warnings": warnings,
        "original_itinerary": original_itinerary,
        "proposed_itinerary": proposed_itinerary,
        "expires_at": (datetime.now(timezone.utc) + PROPOSAL_TTL).isoformat(),
    }
    record = AssistantTripProposal(
        id=payload["proposal_id"],
        user_id=user_id,
        trip_id=trip.id,
        proposal_type=proposal_type,
        status="pending",
        expires_at=datetime.now(timezone.utc) + PROPOSAL_TTL,
        base_revision=trip.itinerary_revision,
        requested_intent=intent.model_dump(mode="json"),
        original_inputs=original_inputs,
        proposed_inputs=proposed_inputs,
        original_itinerary=original_itinerary,
        proposed_itinerary=proposed_itinerary,
        changes=changes,
        budget_comparison=payload["budget_comparison"],
        validation=payload["validation"],
        warnings=warnings,
        summary=summary,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return payload, f"I created a proposal for review. It has not been applied to your saved trip. {summary}."


def _pace_label(preferences: dict | None) -> str:
    value = (preferences or {}).get("travel_pace")
    if not isinstance(value, (int, float)):
        return "Unknown"
    return "Relaxed" if value < 0.34 else "Balanced" if value < 0.67 else "Fast"


def proposal_to_dict(proposal: AssistantTripProposal) -> dict:
    return {
        "proposal_id": proposal.id,
        "type": proposal.proposal_type,
        "status": proposal.status,
        "base_revision": proposal.base_revision,
        "summary": proposal.summary,
        "changes": proposal.changes or [],
        "itinerary_comparison": _itinerary_comparison(proposal.original_itinerary, proposal.proposed_itinerary),
        "budget_comparison": proposal.budget_comparison,
        "validation": proposal.validation,
        "warnings": proposal.warnings or [],
        "original_itinerary": proposal.original_itinerary,
        "proposed_itinerary": proposal.proposed_itinerary,
        "expires_at": proposal.expires_at.isoformat() if proposal.expires_at else None,
    }
