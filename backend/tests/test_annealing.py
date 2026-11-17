from app.schemas import AttractionInput, Preferences
from app.services.annealing import generate_annealed_itinerary


def test_annealing_returns_a_feasible_decoded_itinerary():
    items = [AttractionInput(id=str(i), name=str(i), category="history", latitude=0, longitude=0, cost=10, visit_minutes=30, preference_score=0.8, opening_minute=0, closing_minute=720) for i in range(3)]
    result = generate_annealed_itinerary(items, Preferences(interests={"history": 1}), 0, 0, 100, 120, seed=2)
    assert result["feasible"]
    assert result["risk_score"] is None
    assert result["risk_data_status"] == "unavailable"
