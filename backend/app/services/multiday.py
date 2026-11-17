"""Deterministic multi-day wrapper around the single-day greedy baseline."""

from datetime import timedelta

from app.schemas import AttractionInput, ConfirmedActivity, ItineraryStop, MealBreak, Preferences
from app.services.planner import calculate_attraction_risk, generate_greedy_itinerary, risk_data_status
from app.services.routing import estimate_minutes, build_travel_time_matrix
from app.services.attraction_relevance import unsupported_interests


def generate_multiday_greedy(
    *,
    attractions: list[AttractionInput],
    preferences: Preferences,
    start_date,
    end_date,
    start_latitude: float,
    start_longitude: float,
    budget: float,
    available_minutes_per_day: int,
    meal_breaks: list[MealBreak],
    confirmed_activities: list[ConfirmedActivity],
    routing_provider: str,
    transport_mode: str = "mixed",
    walking_tolerance: float = 0.5,
) -> dict:
    """Allocate attractions across days while preserving fixed reservations."""
    number_of_days = (end_date - start_date).days + 1
    remaining = list(attractions)
    remaining_budget = budget
    break_minutes = sum(item.duration_minutes for item in meal_breaks)
    days = []
    warnings: list[str] = []
    day_start = 540 if available_minutes_per_day >= 540 else 0

    for index in range(number_of_days):
        day_number = index + 1
        days_left = number_of_days - index
        required_ids = {
            item.attraction_id
            for item in confirmed_activities
            if item.day_number == day_number
        }
        reservations = sorted(
            (item for item in confirmed_activities if item.day_number == day_number),
            key=lambda item: item.start_minute,
        )
        by_id = {item.id: item for item in remaining}
        fixed_stops = []
        fixed_cost = 0.0
        fixed_warnings = []
        previous_departure = day_start
        previous_location = (start_latitude, start_longitude)
        for reservation in reservations:
            attraction = by_id.get(reservation.attraction_id)
            if attraction is None:
                fixed_warnings.append(f"Confirmed activity {reservation.attraction_id} is unavailable.")
                continue
            if attraction.opening_window_known is False:
                fixed_warnings.append(f"Opening hours for confirmed activity {attraction.name} are unknown; the 09:00–19:00 planning window is an assumption.")
            if attraction.visit_duration_known is False:
                fixed_warnings.append(f"Visit duration for confirmed activity {attraction.name} is unknown; the category-based planning duration is an assumption.")
            if attraction.data_source == "osm":
                fixed_warnings.append("Transfer times are conservative straight-line estimates with a local travel buffer, not road or traffic estimates.")
            departure = reservation.start_minute + attraction.visit_minutes
            travel_before = estimate_minutes(previous_location, (attraction.latitude, attraction.longitude), transport_mode=transport_mode, walking_tolerance=walking_tolerance)
            if reservation.start_minute < attraction.opening_minute or departure > attraction.closing_minute:
                fixed_warnings.append(f"Confirmed activity {attraction.name} falls outside its opening window.")
            if reservation.start_minute < previous_departure:
                if reservation.start_minute < day_start:
                    fixed_warnings.append(f"Confirmed activity {attraction.name} cannot be reached before its fixed start time.")
                else:
                    fixed_warnings.append(f"Confirmed activity {attraction.name} overlaps another reservation.")
            if travel_before > reservation.start_minute - previous_departure:
                fixed_warnings.append(f"Confirmed activity {attraction.name} cannot be reached before its fixed start time.")
            if departure > available_minutes_per_day:
                fixed_warnings.append(f"Confirmed activity {attraction.name} exceeds the daily time limit.")
            if any(reservation.start_minute < meal.start_minute + meal.duration_minutes and departure > meal.start_minute for meal in meal_breaks):
                fixed_warnings.append(f"Confirmed activity {attraction.name} overlaps a meal break.")
            fixed_stops.append(ItineraryStop(
                attraction_id=attraction.id, name=attraction.name,
                arrival_minute=reservation.start_minute, departure_minute=departure,
                travel_minutes_before=travel_before, wait_minutes=0, cost=attraction.cost,
                preference_score=attraction.preference_score,
                risk_score=calculate_attraction_risk(attraction),
                risk_data_status=risk_data_status([attraction]),
            ))
            fixed_cost += attraction.cost
            previous_departure = max(previous_departure, departure)
            previous_location = (attraction.latitude, attraction.longitude)
        fixed_ids = {stop.attraction_id for stop in fixed_stops}
        flexible_attractions = [item for item in remaining if item.id not in fixed_ids]
        flexible_start = by_id[fixed_stops[-1].attraction_id] if fixed_stops else None
        flexible_minutes = available_minutes_per_day - previous_departure
        daily_budget = remaining_budget / days_left
        if not flexible_attractions or flexible_minutes <= 0:
            result = {"stops": [], "total_cost": 0.0, "total_travel_minutes": 0,
                      "total_visit_minutes": 0, "feasible": True,
                      "warnings": ["No time remains after fixed reservations and meal breaks."] if flexible_minutes <= 0 else []}
        else:
            start = (flexible_start.latitude, flexible_start.longitude) if flexible_start else (start_latitude, start_longitude)
            matrix = build_travel_time_matrix(
                start=start, attractions=flexible_attractions,
                provider=routing_provider,
                transport_mode=transport_mode, walking_tolerance=walking_tolerance,
            )
            result = generate_greedy_itinerary(
                attractions=flexible_attractions, preferences=preferences,
                start_latitude=start[0], start_longitude=start[1],
                budget=max(0, daily_budget - fixed_cost), available_minutes=available_minutes_per_day,
                travel_matrix=matrix, priority_attraction_ids=required_ids,
                blocked_windows=[(item.start_minute, item.start_minute + item.duration_minutes) for item in meal_breaks if item.start_minute >= previous_departure],
                # Spread the remaining catalog over the remaining trip days. This
                # prevents the greedy baseline from consuming a whole catalog on day 1.
                max_stops=min(5, max(0, (len(remaining) + days_left - 1) // days_left - len(fixed_stops))),
                start_minute=previous_departure,
            )
        result["stops"] = [*fixed_stops, *result["stops"]]
        result["total_cost"] += fixed_cost
        result["total_travel_minutes"] += sum(stop.travel_minutes_before for stop in fixed_stops)
        result["total_visit_minutes"] += sum(
            stop.departure_minute - stop.arrival_minute for stop in fixed_stops
        )
        # The day quota intentionally leaves attractions for subsequent dates.
        result["warnings"] = [
            warning for warning in result["warnings"]
            if "attractions were omitted because of budget or time constraints" not in warning
        ]
        result["warnings"].extend(fixed_warnings)

        if fixed_cost > daily_budget + 1e-9:
            result["warnings"].append("Confirmed activities exceed the allocated daily budget.")
        if result["stops"] and result["stops"][-1].departure_minute > available_minutes_per_day:
            result["warnings"].append("The schedule exceeds the daily time limit.")
        if not result["stops"] and not result["warnings"]:
            result["warnings"].append("No available attractions fit this day's time and budget constraints.")

        selected_ids = {stop.attraction_id for stop in result["stops"]}
        missing_required = required_ids - selected_ids
        fixed_violation = any(
            phrase in warning
            for warning in fixed_warnings
            for phrase in ("falls outside its opening window", "overlaps another reservation", "cannot be reached", "exceeds the daily time limit", "overlaps a meal break", "is unavailable")
        )
        day_warnings = list(result["warnings"])
        if missing_required:
            day_warnings.append("Confirmed activities could not be scheduled: " + ", ".join(sorted(missing_required)))
        days.append({
            "day_number": day_number,
            "date": start_date + timedelta(days=index),
            "stops": result["stops"],
            "total_cost": result["total_cost"],
            "total_travel_minutes": result["total_travel_minutes"],
            "total_visit_minutes": result["total_visit_minutes"],
            "reserved_break_minutes": break_minutes,
            "meal_breaks": meal_breaks,
            # Missing observations and unscheduled catalog alternatives are
            # disclosures, not hard schedule violations.
            "feasible": result["feasible"] and not missing_required and not fixed_violation,
            "warnings": day_warnings,
        })
        remaining_budget -= result["total_cost"]
        remaining = [item for item in remaining if item.id not in selected_ids]

    for item in confirmed_activities:
        if item.day_number > number_of_days:
            warnings.append(f"Confirmed activity {item.attraction_id} refers to a day outside the trip.")
    if remaining:
        warnings.append(
            f"{len(remaining)} attractions remain unscheduled after applying daily time and budget limits."
        )
    total_cost = sum(day["total_cost"] for day in days)
    stop_list = [stop for day in days for stop in day["stops"]]
    survival = 1.0
    risk_complete = True
    for stop in stop_list:
        if stop.risk_score is None:
            risk_complete = False
        else:
            survival *= 1 - stop.risk_score
    if stop_list and not risk_complete:
        warnings.append("Risk data is incomplete. The optimizer used a known-components-only proxy; this is not a verified safety assessment.")
        warnings.append("Risk tolerance could not be fully applied because scheduled risk observations are unavailable.")
    unsupported = unsupported_interests(attractions, preferences.interests)
    if unsupported:
        warnings.append("The current attraction catalog cannot represent these selected interests well: " + ", ".join(unsupported) + ".")
    warnings = list(dict.fromkeys(warnings))
    reported = set(warnings)
    for day in days:
        day["warnings"] = [item for item in dict.fromkeys(day["warnings"]) if item not in reported]
        reported.update(day["warnings"])
    return {
        "days": days,
        "total_cost": round(total_cost, 2),
        "total_travel_minutes": sum(day["total_travel_minutes"] for day in days),
        "total_visit_minutes": sum(day["total_visit_minutes"] for day in days),
        "satisfaction": round(sum(stop.preference_score for stop in stop_list) / len(stop_list), 3) if stop_list else 0.0,
        "risk_score": round(1 - survival, 3) if stop_list and risk_complete else None,
        "risk_data_status": risk_data_status([item for item in attractions if item.id in {stop.attraction_id for stop in stop_list}]),
        "feasible": all(day["feasible"] for day in days),
        "warnings": warnings,
    }
