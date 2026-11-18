"""Catalog-backed, bounded attraction selection for assistant proposals."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Attraction, Trip
from app.schemas import AttractionInput, MultiDayOptimizeRequest, Preferences
from app.services.attraction_relevance import interest_match
from app.services.itinerary_candidates import _likely_same_place
from app.services.poi_catalog import to_optimizer_attraction
from app.services.routing import haversine_km
from app.services.assistant.schemas import AssistantIntentOutput


_INTEREST_KEYS = {
    "history", "heritage", "spiritual", "mountains", "nature", "adventure",
    "photography", "food", "wellness", "shopping", "nightlife", "beaches",
}
_MAX_CANDIDATES_PER_OPERATION = 8


class AttractionChangeError(ValueError):
    """A safe user-facing reason an attraction proposal could not be prepared."""


@dataclass
class PreparedAttractionChange:
    request: MultiDayOptimizeRequest
    planning_request: MultiDayOptimizeRequest
    operation: str
    candidate_groups: list[list[AttractionInput]]
    count: int
    target: AttractionInput | None = None
    target_day: int | None = None
    requested_day: int | None = None


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _catalog_attractions(db: Session, trip: Trip) -> list[AttractionInput]:
    rows = db.scalars(
        select(Attraction)
        .where(func.lower(Attraction.destination) == trip.destination.strip().lower())
        .order_by(Attraction.name, Attraction.id)
    ).all()
    result = []
    for row in rows:
        try:
            result.append(AttractionInput.model_validate(to_optimizer_attraction(row)))
        except Exception:
            # Invalid catalog rows are not suitable for planner input and are
            # skipped without fabricating or repairing their source data.
            continue
    return result


def _match_catalog_name(query: str, catalog: list[AttractionInput]) -> AttractionInput:
    normalized = _normalize(query)
    exact = [item for item in catalog if _normalize(item.name) == normalized]
    matches = exact or [item for item in catalog if normalized in _normalize(item.name)]
    if not matches:
        raise AttractionChangeError(
            f"I couldn't find “{query}” in the saved attraction catalog for this destination. "
            "No attraction information was invented, and your trip was not changed."
        )
    if len(matches) > 1:
        names = ", ".join(item.name for item in matches[:4])
        raise AttractionChangeError(
            f"More than one catalog attraction matches “{query}” ({names}). Please name the one you mean."
        )
    return matches[0]


def _match_itinerary_target(
    target_name: str | None,
    day_number: int | None,
    position: str | None,
    itinerary: dict,
) -> tuple[AttractionInput, int]:
    days = itinerary.get("days") or []
    day_numbers = {day.get("day_number") for day in days}
    if day_number is not None and day_number not in day_numbers:
        raise AttractionChangeError(f"Day {day_number} is outside this trip's itinerary.")
    if position == "last":
        day = next((item for item in days if item.get("day_number") == day_number), None)
        stops = (day or {}).get("stops") or []
        if not stops:
            raise AttractionChangeError(f"Day {day_number} has no scheduled attraction to change.")
        selected = stops[-1]
        return _input_for_itinerary_stop(selected, day_number), day_number

    normalized = _normalize(target_name or "")
    matches = []
    for day in days:
        if day_number is not None and day.get("day_number") != day_number:
            continue
        for stop in day.get("stops") or []:
            name = _normalize(str(stop.get("name") or ""))
            if normalized and (name == normalized or normalized in name):
                matches.append((stop, day.get("day_number")))
    if not matches:
        raise AttractionChangeError(
            f"I couldn't find “{target_name}” in the selected day's itinerary. Your trip was not changed."
        )
    if len(matches) > 1:
        options = ", ".join(f"{stop.get('name')} on Day {day}" for stop, day in matches[:4])
        raise AttractionChangeError(f"That name matches more than one scheduled stop ({options}). Which one should I use?")
    stop, selected_day = matches[0]
    return _input_for_itinerary_stop(stop, selected_day), int(selected_day)


def _input_for_itinerary_stop(stop: dict, day_number: int) -> AttractionInput:
    # Itinerary stops do not carry source fields; callers replace this projection
    # with the matching saved planner input before using it for a mutation.
    return AttractionInput(
        id=str(stop.get("attraction_id", "")),
        name=str(stop.get("name", "Attraction")),
        category="other", latitude=0, longitude=0, visit_minutes=max(
            1, int(stop.get("departure_minute", 1)) - int(stop.get("arrival_minute", 0))
        ), preference_score=0.5,
    )


def _find_target_input(target: AttractionInput, request: MultiDayOptimizeRequest) -> AttractionInput:
    return next((item for item in request.attractions if item.id == target.id), target)


def _current_itinerary_request(
    trip: Trip, request: MultiDayOptimizeRequest, *, exclude_ids: set[str] | None = None,
) -> MultiDayOptimizeRequest:
    excluded = exclude_ids or set()
    current_ids = {
        str(stop.get("attraction_id"))
        for day in ((trip.latest_itinerary or {}).get("days") or [])
        for stop in day.get("stops", [])
    } - excluded
    current_ids.update(
        item.attraction_id for item in request.confirmed_activities if item.attraction_id not in excluded
    )
    by_id = {item.id: item for item in request.attractions}
    missing = current_ids - by_id.keys()
    if missing:
        raise AttractionChangeError(
            "The saved planner data is missing one or more current itinerary attractions, so I couldn't safely propose this change."
        )
    active = [item for item in request.attractions if item.id in current_ids]
    if not active:
        raise AttractionChangeError("The planner needs at least one current attraction to build this itinerary proposal.")
    return request.model_copy(update={"attractions": active})


def _rank_for_category(
    candidates: list[AttractionInput], category: str, preferences: Preferences,
) -> list[AttractionInput]:
    return sorted(
        candidates,
        key=lambda item: (
            -interest_match(item, {category: 1.0}),
            -interest_match(item, preferences.interests),
            -(item.priority_score if item.priority_score is not None else item.preference_score),
            item.name.casefold(), item.id,
        ),
    )


def _available_candidates(
    candidates: list[AttractionInput],
    request: MultiDayOptimizeRequest,
    scheduled_ids: set[str],
    target: AttractionInput | None = None,
) -> list[AttractionInput]:
    existing = list(request.attractions)
    chosen = []
    for candidate in candidates:
        if candidate.id in scheduled_ids or (target is not None and candidate.id == target.id):
            continue
        if any(_normalize(candidate.name) == _normalize(item.name) for item in existing if item.id in scheduled_ids):
            continue
        if any(_likely_same_place(candidate, item) for item in existing if item.id in scheduled_ids):
            continue
        if all(item.id != candidate.id for item in chosen):
            chosen.append(candidate)
    return chosen


def _category_candidates(
    catalog: list[AttractionInput], category: str, request: MultiDayOptimizeRequest,
    scheduled_ids: set[str], preferences: Preferences, target: AttractionInput | None = None,
) -> list[AttractionInput]:
    available = _available_candidates(catalog, request, scheduled_ids, target)
    if category == "less_crowded":
        available = [item for item in available if item.crowd_risk_known is True]
        return sorted(available, key=lambda item: (item.crowd_risk, item.name.casefold(), item.id))
    relevant = [item for item in available if interest_match(item, {category: 1.0}) > 0]
    return _rank_for_category(relevant, category, preferences)[:_MAX_CANDIDATES_PER_OPERATION]


def prepare_attraction_change(
    db: Session,
    trip: Trip,
    request: MultiDayOptimizeRequest,
    intent: AssistantIntentOutput,
) -> PreparedAttractionChange:
    params = intent.parameters
    operation = params["operation"]
    catalog = _catalog_attractions(db, trip)
    current_days = (trip.latest_itinerary or {}).get("days") or []
    scheduled_ids = {
        str(stop.get("attraction_id"))
        for day in current_days for stop in (day.get("stops") or [])
    }
    trip_days = {int(day.get("day_number")) for day in current_days if isinstance(day.get("day_number"), int)}
    requested_day = params.get("day_number")
    if requested_day is not None and requested_day not in trip_days:
        raise AttractionChangeError(f"Day {requested_day} is outside this trip's itinerary.")

    preferences = Preferences.model_validate(trip.preferences or {})
    if operation == "add":
        if not catalog:
            raise AttractionChangeError("The saved attraction catalog for this destination is empty. No change was made.")
        if params.get("attraction_name"):
            candidate = _match_catalog_name(params["attraction_name"], catalog)
            if candidate.id in scheduled_ids:
                raise AttractionChangeError(f"{candidate.name} is already in your itinerary.")
            groups = [[candidate]]
            count = 1
        else:
            category = params["category"]
            count = int(params.get("count", 1))
            candidates = _category_candidates(catalog, category, request, scheduled_ids, preferences)
            if len(candidates) < count:
                if not candidates:
                    raise AttractionChangeError(
                        f"The saved destination catalog has no suitable unscheduled attractions for {category}. No change was made."
                    )
                raise AttractionChangeError(
                    f"The saved destination catalog has only {len(candidates)} suitable unscheduled attraction(s) for {category}; I couldn't safely add {count}."
                )
            groups = [candidates for _ in range(count)]
        try:
            planning_request = _current_itinerary_request(trip, request)
        except AttractionChangeError:
            if scheduled_ids or request.confirmed_activities:
                raise
            # An empty saved itinerary can still receive a catalog-backed first
            # activity. Limit the temporary plan to the requested candidate so
            # unrelated unscheduled planner options are not added as side effects.
            planning_request = request.model_copy(update={
                "attractions": [groups[0][0]], "confirmed_activities": [],
            })
        return PreparedAttractionChange(
            request, planning_request, operation, groups, count, requested_day=requested_day,
        )

    target, target_day = _match_itinerary_target(
        params.get("target_name"), requested_day, params.get("position"), trip.latest_itinerary or {},
    )
    target = _find_target_input(target, request)
    if target.id in {str(value) for value in (trip.completed_attraction_ids or [])}:
        raise AttractionChangeError(f"{target.name} is completed and cannot be removed or replaced.")
    if not any(item.id == target.id for item in request.attractions):
        raise AttractionChangeError(f"The planner data for {target.name} is missing, so I couldn't safely change it.")

    remaining = [item for item in request.attractions if item.id != target.id]
    confirmations = [item for item in request.confirmed_activities if item.attraction_id != target.id]
    if operation == "remove":
        if not remaining:
            raise AttractionChangeError("This is the last attraction in the saved planner data; it cannot create an empty itinerary proposal.")
        updated = request.model_copy(update={"attractions": remaining, "confirmed_activities": confirmations})
        planning_request = _current_itinerary_request(trip, updated, exclude_ids={target.id})
        return PreparedAttractionChange(
            updated, planning_request, operation, [], 0, target=target, target_day=target_day,
        )

    if params.get("replacement_name"):
        candidate = _match_catalog_name(params["replacement_name"], catalog)
        candidates = [candidate]
    elif params.get("category"):
        candidates = _category_candidates(
            catalog, params["category"], request, scheduled_ids - {target.id}, preferences, target,
        )
    elif params.get("criterion") == "less_crowded":
        candidates = _category_candidates(
            catalog, "less_crowded", request, scheduled_ids - {target.id}, preferences, target,
        )
    else:
        candidates = _available_candidates(
            catalog, request, scheduled_ids - {target.id}, target,
        )
        candidates.sort(key=lambda item: (
            haversine_km((target.latitude, target.longitude), (item.latitude, item.longitude)),
            item.name.casefold(), item.id,
        ))
    candidates = [item for item in candidates if item.id != target.id]
    if params.get("replacement_name") and candidate.id in scheduled_ids - {target.id}:
        raise AttractionChangeError(f"{candidate.name} is already in your itinerary.")
    if not candidates:
        if params.get("criterion") == "less_crowded":
            raise AttractionChangeError("No unscheduled replacement has known crowd data, so I can't verify that it is less crowded.")
        raise AttractionChangeError("No suitable unscheduled catalog attraction was found for this replacement.")
    if not remaining:
        raise AttractionChangeError("The planner needs at least one other attraction to build a replacement proposal.")
    updated = request.model_copy(update={"attractions": remaining, "confirmed_activities": confirmations})
    try:
        planning_request = _current_itinerary_request(trip, updated, exclude_ids={target.id})
    except AttractionChangeError:
        other_scheduled = scheduled_ids - {target.id}
        if other_scheduled or confirmations:
            raise
        planning_request = updated.model_copy(update={
            "attractions": [candidates[0]], "confirmed_activities": [],
        })
    return PreparedAttractionChange(
        updated, planning_request, operation, [candidates[:_MAX_CANDIDATES_PER_OPERATION]], 1,
        target=target, target_day=target_day, requested_day=target_day,
    )
