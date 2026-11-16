from app.schemas import AttractionInput, Disruption
from app.services.disruptions import apply_disruptions


def test_disruptions_raise_risk_close_attractions_and_adjust_travel_time():
    attraction = AttractionInput(
        id="museum", name="Museum", category="history", latitude=17.385,
        longitude=78.4867, visit_minutes=60, preference_score=0.8,
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
    assert matrix[0][1] == 15
    assert "closed-place" in closed
    assert len(applied) == 3
