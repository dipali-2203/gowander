
from math import asin, cos, isfinite, radians, sin, sqrt, ceil

from app.schemas import (
    AttractionInput,
    ItineraryStop,
    Preferences,
)

from app.services.routing import TravelMatrix, build_travel_time_matrix
from app.services.constraints import validate_itinerary
from app.services.attraction_relevance import category_diversity_factor, inferred_walking_effort, interest_match, unsupported_interests


def distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Calculate straight-line distance using the Haversine formula."""
    lat1, lon1, lat2, lon2 = map(
        radians, [lat1, lon1, lat2, lon2]
    )

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    )

    # Protect against floating-point rounding.
    a = min(1.0, max(0.0, a))

    return 6371.0 * 2 * asin(sqrt(a))


def estimate_travel_minutes(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> int:
    """
    Temporary estimate based on straight-line distance.
    Replace this function with a routing-matrix lookup later.
    """
    km = distance_km(lat1, lon1, lat2, lon2)
    return ceil(km / 25.0 * 60.0)


def calculate_attraction_risk(
    attraction: AttractionInput,
) -> float | None:
    """
    Baseline probability of at least one disruption.
    Assumes independent weather, crowd, and availability risks.
    """
    fields = (("weather_risk", attraction.weather_risk_known), ("crowd_risk", attraction.crowd_risk_known), ("availability_risk", attraction.availability_risk_known))
    risks = [getattr(attraction, field) for field, known in fields if known]
    if len(risks) != len(fields):
        return None

    survival = 1.0
    for risk in risks:
        survival *= 1.0 - risk

    return 1.0 - survival


def optimizer_risk_proxy(attraction: AttractionInput) -> float:
    """Known-components-only proxy; unknown dimensions contribute neutral 0 in legacy objectives."""
    survival = 1.0
    for field in ("weather_risk", "crowd_risk", "availability_risk"):
        if getattr(attraction, f"{field}_known"):
            survival *= 1.0 - getattr(attraction, field)
    return 1.0 - survival


def risk_data_status(attractions: list[AttractionInput]) -> str:
    if not attractions:
        return "not_applicable"
    known = [getattr(item, f"{field}_known") for item in attractions for field in ("weather_risk", "crowd_risk", "availability_risk")]
    if not any(known):
        return "unavailable"
    if not all(known):
        return "partial"
    return "verified" if all(
        isinstance(item.risk_metadata.get(key), dict)
        and item.risk_metadata[key].get("verified") is True
        and item.risk_metadata[key].get("source")
        and item.risk_metadata[key].get("observed_at")
        for item in attractions for key in ("weather", "crowd", "availability")
    ) else "assumed"


def generate_greedy_itinerary(
    attractions: list[AttractionInput],
    preferences: Preferences,
    start_latitude: float,
    start_longitude: float,
    budget: float,
    available_minutes: int,
    travel_matrix: TravelMatrix | None = None,
    priority_attraction_ids: set[str] | None = None,
    blocked_windows: list[tuple[int, int]] | None = None,
    max_stops: int | None = 5,
    start_minute: int = 0,
) -> dict:
    """Generate a feasible greedy itinerary for one planning day."""

    if len({a.id for a in attractions}) != len(attractions):
        raise ValueError("Attraction IDs must be unique.")

    numbers = [
        start_latitude,
        start_longitude,
        budget,
        float(available_minutes),
    ]

    if not all(isfinite(value) for value in numbers):
        raise ValueError("Planning inputs must be finite numbers.")

    if budget < 0 or available_minutes <= 0:
        raise ValueError(
            "Budget must be non-negative and available time positive."
        )

    # Build a fallback matrix when one is not provided.
    if travel_matrix is None:
        travel_matrix = build_travel_time_matrix(
            start=(start_latitude, start_longitude),
            attractions=attractions,
            provider="haversine",
        )

    expected_size = len(attractions) + 1

    if (
        len(travel_matrix) != expected_size
        or any(len(row) != expected_size for row in travel_matrix)
    ):
        raise ValueError(
            "Travel matrix dimensions do not match locations."
        )

    # Index 0 represents the starting location.
    # Attraction indices correspond to their positions in the matrix.
    attraction_indices = {
        attraction.id: index + 1
        for index, attraction in enumerate(attractions)
    }

    remaining = list(attractions)
    stops: list[ItineraryStop] = []

    current_index = 0
    elapsed = start_minute
    spent = 0.0
    category_counts: dict[str, int] = {}
    pace_limit = 3 if preferences.travel_pace < 0.34 else 4 if preferences.travel_pace < 0.67 else 5
    stop_limit = min(max_stops if max_stops is not None else 5, pace_limit, 5)

    while remaining and len(stops) < stop_limit:
        candidates = []

        for attraction in remaining:
            attraction_index = attraction_indices[attraction.id]

            travel = travel_matrix[current_index][attraction_index]

            if travel is None:
                continue

            arrival = elapsed + travel
            wait = max(0, attraction.opening_minute - arrival)
            scheduled_arrival = arrival + wait
            if blocked_windows:
                for block_start, block_end in sorted(blocked_windows):
                    if scheduled_arrival < block_end and scheduled_arrival + attraction.visit_minutes > block_start:
                        scheduled_arrival = block_end
            departure = scheduled_arrival + attraction.visit_minutes
            required_minutes = departure - elapsed

            if spent + attraction.cost > budget:
                continue

            if departure > available_minutes:
                continue

            if departure > attraction.closing_minute:
                continue

            priority = attraction.priority_score if attraction.priority_score is not None else attraction.preference_score
            fit = interest_match(attraction, preferences.interests)
            diversity = category_diversity_factor(attraction, category_counts)
            effort = inferred_walking_effort(attraction) if attraction.data_source == "osm" else attraction.fatigue_score
            utility = attraction.preference_score * (0.7 + 0.6 * fit) * diversity * (0.75 + 0.5 * priority)

            risk = optimizer_risk_proxy(attraction)

            # Risk-averse travelers receive a stronger risk penalty.
            risk_penalty = 1.0 - preferences.risk_tolerance
            crowd_penalty = (attraction.crowd_risk if attraction.crowd_risk_known else 0.0) * (1.0 - preferences.crowd_tolerance)
            cost_penalty = (attraction.cost / max(budget, 1)) * preferences.budget_sensitivity
            fatigue_penalty = effort * (1.0 - preferences.walking_tolerance)

            risk_adjusted_utility = utility * (
                1.0 - risk * risk_penalty - crowd_penalty - cost_penalty - fatigue_penalty
            )

            score = risk_adjusted_utility / max(required_minutes, 1) + (priority - 0.5) * 0.01
            if priority_attraction_ids and attraction.id in priority_attraction_ids:
                score += 100.0

            candidates.append(
                (
                    score,
                    attraction,
                    travel,
                    risk,
                    attraction_index,
                    scheduled_arrival - arrival,
                )
            )

        if not candidates:
            break

        # Deterministic tie-breaking makes baseline tests reproducible.
        candidates.sort(
            key=lambda item: (
                -item[0],
                item[1].id,
            )
        )

        _, selected, travel, risk, selected_index, wait = candidates[0]

        arrival = elapsed + travel
        scheduled_arrival = arrival + wait
        departure = scheduled_arrival + selected.visit_minutes

        stops.append(
            ItineraryStop(
                attraction_id=selected.id,
                name=selected.name,
                arrival_minute=scheduled_arrival,
                departure_minute=departure,
                travel_minutes_before=travel,
                cost=selected.cost,
                preference_score=selected.preference_score,
                risk_score=calculate_attraction_risk(selected),
                risk_data_status=risk_data_status([selected]),
                wait_minutes=wait,
            )
        )

        elapsed = departure
        spent += selected.cost
        current_index = selected_index
        selected_category = (selected.catalog_category or selected.category).lower()
        category_counts[selected_category] = category_counts.get(selected_category, 0) + 1
        remaining.remove(selected)

    total_travel = sum(
        stop.travel_minutes_before for stop in stops
    )

    total_visit = sum(
        stop.departure_minute - stop.arrival_minute
        for stop in stops
    )

    satisfaction = (
        sum(stop.preference_score for stop in stops) / len(stops)
        if stops else 0.0
    )

    trip_survival = 1.0
    risk_complete = True
    for stop in stops:
        if stop.risk_score is None:
            risk_complete = False
        else:
            trip_survival *= 1.0 - stop.risk_score

    warnings = []

    if any(attraction.opening_window_known is False for attraction in remaining + [stop_attraction for stop_attraction in attractions if stop_attraction.id in {stop.attraction_id for stop in stops}]):
        warnings.append("Some opening hours are unknown; the 09:00–19:00 planning window is an assumption, not verified business hours.")
    if any(attraction.visit_duration_known is False for attraction in attractions if attraction.id in {stop.attraction_id for stop in stops}):
        warnings.append("Some visit durations are unknown; category-based planning estimates are assumptions.")
    if any(attraction.data_source == "osm" for attraction in attractions):
        warnings.append("Transfer times are conservative straight-line estimates with a local travel buffer, not road or traffic estimates.")

    if not stops:
        warnings.append(
            "No attractions fit the available budget and time."
        )
    if stops and not risk_complete:
        warnings.append("Risk data is incomplete. The optimizer used a known-components-only proxy; this is not a verified safety assessment.")
        warnings.append("Risk tolerance could not be fully applied because scheduled risk observations are unavailable.")
    if any(attraction.data_source == "osm" for attraction in attractions) and stops:
        if any(stop.risk_data_status == "unavailable" for stop in stops):
            warnings.append("Crowd tolerance cannot be fully optimized because crowd observations are unavailable.")
        if preferences.walking_tolerance < 0.5:
            warnings.append("Walking effort is estimated from attraction categories and OSM activity tags, not measured accessibility or terrain data.")
    unsupported = unsupported_interests(attractions, preferences.interests)
    if unsupported:
        warnings.append("The current attraction catalog cannot represent these selected interests well: " + ", ".join(unsupported) + ".")
    if remaining:
        warnings.append(
            f"{len(remaining)} attractions were omitted because "
            "of budget or time constraints."
        )

    constraint_violations = validate_itinerary(
        stops=stops,
        attractions=attractions,
        budget=budget,
        available_minutes=available_minutes,
    )
    warnings.extend(constraint_violations)

    # Feasible means the selected itinerary obeys these hard limits.
    feasible = (
        len(stops) > 0
        and not constraint_violations
    )

    return {
        "stops": stops,
        "total_cost": round(spent, 2),
        "total_travel_minutes": total_travel,
        "total_visit_minutes": total_visit,
        "satisfaction": round(satisfaction, 3),
        "risk_score": round(1.0 - trip_survival, 3) if stops and risk_complete else None,
        "risk_data_status": risk_data_status([next(a for a in attractions if a.id == stop.attraction_id) for stop in stops]),
        "feasible": feasible,
        "warnings": warnings,
    }
