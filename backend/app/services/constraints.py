"""Hard-constraint validation kept independent from route selection."""

from app.schemas import AttractionInput, ItineraryStop


def validate_itinerary(
    stops: list[ItineraryStop],
    attractions: list[AttractionInput],
    budget: float,
    available_minutes: int,
) -> list[str]:
    """Return human-readable hard-constraint violations for one planning day."""
    by_id = {attraction.id: attraction for attraction in attractions}
    violations: list[str] = []

    if sum(stop.cost for stop in stops) > budget + 1e-9:
        violations.append("Selected attractions exceed the available budget.")

    if stops and stops[-1].departure_minute > available_minutes:
        violations.append("Selected attractions exceed the daily time limit.")

    for stop in stops:
        attraction = by_id[stop.attraction_id]
        if stop.arrival_minute < attraction.opening_minute:
            violations.append(f"{stop.name} is scheduled before opening time.")
        if stop.departure_minute > attraction.closing_minute:
            violations.append(f"{stop.name} is scheduled after closing time.")

    return violations
