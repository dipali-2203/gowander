from app.schemas import AttractionInput, Preferences
from app.services.planner import generate_greedy_itinerary


def test_low_walking_tolerance_avoids_high_fatigue_when_otherwise_equal():
    attractions = [
        AttractionInput(id="high", name="Steep walk", category="history", latitude=17.385, longitude=78.4867, cost=0, visit_minutes=60, preference_score=0.8, fatigue_score=1, opening_minute=0, closing_minute=720),
        AttractionInput(id="low", name="Easy museum", category="history", latitude=17.385, longitude=78.4867, cost=0, visit_minutes=60, preference_score=0.8, fatigue_score=0, opening_minute=0, closing_minute=720),
    ]
    result = generate_greedy_itinerary(attractions, Preferences(interests={"history": 1}, walking_tolerance=0, travel_pace=0), 17.385, 78.4867, 100, 60)
    assert result["stops"][0].attraction_id == "low"
