from datetime import date

import pytest

from app.schemas import AttractionInput, ConfirmedActivity, MealBreak, Preferences
from app.services.multiday import generate_multiday_greedy


def test_multiday_planner_reserves_meal_time_and_prioritizes_commitment():
    attractions = [
        AttractionInput(
            id="committed", name="Committed museum", category="history",
            latitude=17.385, longitude=78.4867, cost=100, visit_minutes=60,
            preference_score=0.4, opening_minute=0, closing_minute=720,
        ),
        AttractionInput(
            id="optional", name="Optional gallery", category="history",
            latitude=17.386, longitude=78.4868, cost=100, visit_minutes=60,
            preference_score=1.0, opening_minute=0, closing_minute=720,
        ),
    ]

    result = generate_multiday_greedy(
        attractions=attractions,
        preferences=Preferences(interests={"history": 1.0}),
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 2),
        start_latitude=17.385, start_longitude=78.4867, budget=500,
        available_minutes_per_day=240,
        meal_breaks=[MealBreak(start_minute=120, duration_minutes=30)],
        confirmed_activities=[ConfirmedActivity(attraction_id="committed", day_number=1, start_minute=30)],
        routing_provider="haversine",
    )

    assert len(result["days"]) == 2
    assert result["days"][0]["reserved_break_minutes"] == 30
    assert result["days"][0]["stops"][0].attraction_id == "committed"
    assert result["days"][0]["stops"][0].arrival_minute == 30


def test_confirmed_activity_overlapping_meal_is_marked_infeasible():
    attraction = AttractionInput(id="fixed", name="Fixed", category="history", latitude=17.385, longitude=78.4867, cost=0, visit_minutes=60, preference_score=1, opening_minute=0, closing_minute=720)
    result = generate_multiday_greedy(
        attractions=[attraction], preferences=Preferences(), start_date=date(2026, 11, 1), end_date=date(2026, 11, 1),
        start_latitude=17.385, start_longitude=78.4867, budget=100, available_minutes_per_day=240,
        meal_breaks=[MealBreak(start_minute=30, duration_minutes=30)],
        confirmed_activities=[ConfirmedActivity(attraction_id="fixed", day_number=1, start_minute=20)], routing_provider="haversine",
    )
    assert result["days"][0]["feasible"] is False
    assert "overlaps a meal break" in result["days"][0]["warnings"][0]


def test_unreachable_fixed_reservation_is_marked_infeasible():
    attraction = AttractionInput(id="far", name="Far", category="history", latitude=18, longitude=79, cost=0, visit_minutes=60, preference_score=1, opening_minute=0, closing_minute=720)
    result = generate_multiday_greedy(
        attractions=[attraction], preferences=Preferences(), start_date=date(2026, 11, 1), end_date=date(2026, 11, 1),
        start_latitude=17.385, start_longitude=78.4867, budget=100, available_minutes_per_day=720,
        meal_breaks=[], confirmed_activities=[ConfirmedActivity(attraction_id="far", day_number=1, start_minute=1)], routing_provider="haversine",
    )
    assert result["days"][0]["feasible"] is False
    assert "cannot be reached" in result["days"][0]["warnings"][0]


@pytest.mark.parametrize("days", [1, 3, 5, 7])
def test_multi_day_baseline_distributes_feasible_attractions(days):
    attractions = [
        AttractionInput(
            id=f"place-{index}", name=f"Place {index}", category="history",
            latitude=17.385, longitude=78.4867, cost=100, visit_minutes=60,
            preference_score=0.8, opening_minute=0, closing_minute=1200,
        )
        for index in range(days * 2)
    ]
    result = generate_multiday_greedy(
        attractions=attractions, preferences=Preferences(),
        start_date=date(2026, 11, 1), end_date=date(2026, 11, days),
        start_latitude=17.385, start_longitude=78.4867,
        budget=days * 200, available_minutes_per_day=720,
        meal_breaks=[], confirmed_activities=[], routing_provider="haversine",
    )

    assert len(result["days"]) == days
    assert all(day["stops"] for day in result["days"])
    assert len({stop.attraction_id for day in result["days"] for stop in day["stops"]}) == days * 2
    assert result["total_cost"] == days * 200
    assert result["feasible"] is True
    assert result["risk_score"] is None
    assert result["risk_data_status"] == "unavailable"


def test_meal_break_is_returned_and_reserved_between_activities():
    attractions = [
        AttractionInput(
            id=f"place-{index}", name=f"Place {index}", category="history",
            latitude=17.385, longitude=78.4867, cost=0, visit_minutes=60,
            preference_score=0.8, opening_minute=0, closing_minute=720,
        )
        for index in range(2)
    ]
    result = generate_multiday_greedy(
        attractions=attractions, preferences=Preferences(),
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 1),
        start_latitude=17.385, start_longitude=78.4867, budget=100,
        available_minutes_per_day=240,
        meal_breaks=[MealBreak(start_minute=60, duration_minutes=30)],
        confirmed_activities=[], routing_provider="haversine",
    )

    day = result["days"][0]
    assert day["meal_breaks"] == [MealBreak(start_minute=60, duration_minutes=30)]
    assert day["stops"][1].arrival_minute >= 90
    assert "meal or rest break" in day["stops"][1].wait_reason


def test_catalog_larger_than_trip_capacity_is_reported():
    attractions = [
        AttractionInput(
            id=f"place-{index}", name=f"Place {index}", category="history",
            latitude=17.385, longitude=78.4867, cost=100, visit_minutes=240,
            preference_score=0.8, opening_minute=0, closing_minute=720,
        )
        for index in range(3)
    ]
    result = generate_multiday_greedy(
        attractions=attractions, preferences=Preferences(),
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 1),
        start_latitude=17.385, start_longitude=78.4867, budget=1000,
        available_minutes_per_day=240,
        meal_breaks=[], confirmed_activities=[], routing_provider="haversine",
    )

    assert result["feasible"] is True
    assert "remain unscheduled" in result["warnings"][0]


def test_three_day_udaipur_regression_uses_unknown_hours_as_assumptions():
    attractions = [
        AttractionInput(
            id=f"udaipur-{index}", name=name, category=category, catalog_category=category,
            latitude=latitude, longitude=longitude, cost=0, visit_minutes=60,
            preference_score=0.8, data_source="osm", opening_minute=540,
            closing_minute=1140, opening_window_known=False, visit_duration_known=False,
        )
        for index, (name, category, latitude, longitude) in enumerate([
            ("City Palace", "museum", 24.5764, 73.6835),
            ("Bagore ki Haveli", "historical", 24.5791, 73.6806),
            ("Saheliyon ki Bari", "park", 24.6017, 73.6957),
        ])
    ]
    result = generate_multiday_greedy(
        attractions=attractions, preferences=Preferences(),
        start_date=date(2026, 12, 1), end_date=date(2026, 12, 3),
        start_latitude=24.5854, start_longitude=73.7125, budget=5000,
        available_minutes_per_day=1140,
        meal_breaks=[MealBreak(start_minute=780, duration_minutes=60)],
        confirmed_activities=[], routing_provider="haversine",
    )
    stops = [stop for day in result["days"] for stop in day["stops"]]
    assert len(stops) == 3
    assert len({stop.attraction_id for stop in stops}) == 3
    assert all(stop.wait_minutes == 0 for stop in stops)
    assert all(day["meal_breaks"] for day in result["days"])
