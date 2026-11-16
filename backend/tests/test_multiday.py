from datetime import date

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
