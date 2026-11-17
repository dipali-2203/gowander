from app.schemas import AttractionInput, Disruption
from app.services.disruptions import apply_disruptions
from app.services.planner import generate_greedy_itinerary
from app.schemas import Preferences


def test_disruptions_raise_risk_close_attractions_and_adjust_travel_time():
    attraction = AttractionInput(
        id="museum", name="Museum", category="history", latitude=17.385,
        longitude=78.4867, visit_minutes=60, preference_score=0.8,
        opening_minute=0, closing_minute=240,
    )
    updated, matrix, closed, applied = apply_disruptions(
        [attraction],
        [
            Disruption(kind="rainfall", severity=0.4, affected_attraction_ids=["museum"]),
            Disruption(kind="traffic", severity=0.5),
            Disruption(kind="closure", affected_attraction_ids=["closed-place"]),
        ],
        [[0, 10], [10, 0]],
    )

    assert updated[0].weather_risk == 0.4
    assert updated[0].weather_risk_known is True
    assert updated[0].risk_metadata["weather"]["source"] == "scenario"
    replanned = generate_greedy_itinerary(updated, Preferences(), 17.385, 78.4867, 1000, 240, matrix)
    assert replanned["risk_score"] is None
    assert replanned["risk_data_status"] == "partial"
    assert matrix[0][1] == 15
    assert "closed-place" in closed
    assert len(applied) == 3
