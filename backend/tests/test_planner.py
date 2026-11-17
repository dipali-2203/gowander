
from app.schemas import AttractionInput, Preferences
from app.services.planner import generate_greedy_itinerary


import pytest

from app.schemas import AttractionInput, Preferences
from app.services.planner import (
    calculate_attraction_risk,
    generate_greedy_itinerary,
    risk_data_status,
)


def make_attraction(
    attraction_id: str,
    *,
    cost: float = 100,
    risk: float = 0.0,
) -> AttractionInput:
    return AttractionInput(
        id=attraction_id,
        name=f"Place {attraction_id}",
        category="history",
        latitude=17.385,
        longitude=78.4867,
        cost=cost,
        visit_minutes=60,
        preference_score=0.9,
        weather_risk=risk,
        crowd_risk=0.0,
        availability_risk=0.0,
    )


def test_duplicate_attraction_ids_are_rejected():
    attraction = make_attraction("museum")

    with pytest.raises(ValueError, match="unique"):
        generate_greedy_itinerary(
            attractions=[attraction, attraction],
            preferences=Preferences(),
            start_latitude=17.385,
            start_longitude=78.4867,
            budget=1000,
            available_minutes=240,
        )


def test_no_feasible_attractions_returns_warning():
    result = generate_greedy_itinerary(
        attractions=[make_attraction("expensive", cost=5000)],
        preferences=Preferences(),
        start_latitude=17.385,
        start_longitude=78.4867,
        budget=100,
        available_minutes=240,
    )

    assert result["stops"] == []
    assert result["feasible"] is False
    assert result["total_cost"] == 0
    assert result["warnings"]


def test_attraction_risk_calculation():
    attraction = make_attraction("museum", risk=0.2)

    risk = calculate_attraction_risk(attraction)

    assert risk == pytest.approx(0.2)


def test_unknown_risk_is_not_verified_zero_and_known_zero_is_distinct():
    from app.services.planner import optimizer_risk_proxy

    unknown = AttractionInput(id="unknown", name="Unknown", category="history", latitude=0, longitude=0, visit_minutes=30, preference_score=0.5, data_source="osm")
    known_zero = AttractionInput(id="zero", name="Zero", category="history", latitude=0, longitude=0, visit_minutes=30, preference_score=0.5, weather_risk=0, crowd_risk=0, availability_risk=0)
    known_nonzero = AttractionInput(id="risk", name="Risk", category="history", latitude=0, longitude=0, visit_minutes=30, preference_score=0.5, weather_risk=0.2, crowd_risk=0, availability_risk=0)

    assert calculate_attraction_risk(unknown) is None
    assert optimizer_risk_proxy(unknown) == 0
    assert calculate_attraction_risk(known_zero) == 0
    assert calculate_attraction_risk(known_nonzero) == pytest.approx(0.2)
    assert risk_data_status([known_zero]) == "assumed"
    known_zero.risk_metadata = {
        key: {"verified": True, "source": "field_observation", "observed_at": "2026-11-17T00:00:00Z"}
        for key in ("weather", "crowd", "availability")
    }
    assert risk_data_status([known_zero]) == "verified"

    unknown.opening_minute = 0
    unknown.closing_minute = 240
    plan = generate_greedy_itinerary([unknown], Preferences(), 0, 0, 1000, 240)
    assert plan["risk_score"] is None
    assert plan["risk_data_status"] == "unavailable"
    assert any("known-components-only proxy" in warning for warning in plan["warnings"])


def test_planner_respects_budget():
    attractions = [
        AttractionInput(
            id="expensive",
            name="Expensive Attraction",
            category="history",
            latitude=17.38,
            longitude=78.48,
            cost=5000,
            visit_minutes=60,
            preference_score=1.0,
        ),
        AttractionInput(
            id="affordable",
            name="Affordable Attraction",
            category="history",
            latitude=17.39,
            longitude=78.49,
            cost=100,
            visit_minutes=60,
            preference_score=0.9,
        ),
    ]

    result = generate_greedy_itinerary(
        attractions=attractions,
        preferences=Preferences(
            interests={"history": 1.0},
            risk_tolerance=0.2,
            walking_tolerance=0.5,
        ),
        start_latitude=17.385,
        start_longitude=78.4867,
        budget=200,
        available_minutes=240,
    )

    assert result["total_cost"] <= 200
    assert all(stop.cost <= 200 for stop in result["stops"])
    assert all(stop.arrival_minute >= 0 for stop in result["stops"])


def test_planner_respects_opening_hours():
    attraction = make_attraction("late-opening")
    attraction.opening_minute = 120

    result = generate_greedy_itinerary(
        attractions=[attraction],
        preferences=Preferences(),
        start_latitude=17.385,
        start_longitude=78.4867,
        budget=500,
        available_minutes=240,
    )

    assert result["stops"][0].arrival_minute >= 120
    assert result["feasible"] is True


def test_itinerary_can_use_explicit_nine_to_seven_planning_window():
    attraction = make_attraction("morning")
    attraction.opening_minute = 540
    attraction.closing_minute = 1140
    result = generate_greedy_itinerary(
        [attraction], Preferences(), 17.385, 78.4867, 500, 1140,
        start_minute=540,
    )
    assert result["stops"]
    assert result["stops"][0].arrival_minute >= 540
    assert result["stops"][-1].departure_minute <= 1140


def test_default_candidate_limit_keeps_large_catalogs_browsable_elsewhere():
    attractions = [make_attraction(f"place-{i}") for i in range(8)]
    for item in attractions:
        item.closing_minute = 1140
    result = generate_greedy_itinerary(
        attractions, Preferences(), 17.385, 78.4867, 5000, 1140,
        start_minute=540,
    )
    assert len(result["stops"]) <= 5
    assert "remain" not in " ".join(result["warnings"])


def test_travel_pace_controls_reasonable_stop_count():
    attractions = [make_attraction(f"pace-{i}") for i in range(8)]
    for item in attractions:
        item.closing_minute = 1140
    slow = generate_greedy_itinerary(
        attractions, Preferences(travel_pace=0.2), 17.385, 78.4867, 5000, 1140,
        start_minute=540,
    )
    fast = generate_greedy_itinerary(
        attractions, Preferences(travel_pace=0.9), 17.385, 78.4867, 5000, 1140,
        start_minute=540,
    )
    assert len(slow["stops"]) <= 3
    assert len(fast["stops"]) <= 5
    assert len(slow["stops"]) < len(fast["stops"])
