from app.schemas import AttractionInput, Preferences
from app.services.planner import generate_greedy_itinerary


def test_meal_window_moves_conflicting_visit_after_break():
    attraction = AttractionInput(id="a", name="Museum", category="history", latitude=17.385, longitude=78.4867, cost=0, visit_minutes=60, preference_score=1, opening_minute=0, closing_minute=720)
    result = generate_greedy_itinerary([attraction], Preferences(interests={"history": 1}), 17.385, 78.4867, 100, 240, blocked_windows=[(30, 90)])
    assert result["stops"][0].arrival_minute == 90
