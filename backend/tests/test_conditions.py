from app.schemas import AttractionInput
from app.schemas import AttractionCondition, RiskSimulationResponse
from app.services.conditions import estimated_conditions


def test_estimated_conditions_identify_their_source():
    result = estimated_conditions([AttractionInput(id="a", name="A", category="history", latitude=0, longitude=0, visit_minutes=30, preference_score=0.5)])
    assert result["source"] == "estimated"
    assert result["conditions"][0]["attraction_id"] == "a"
    assert result["conditions"][0]["weather_risk"] is None
    assert result["conditions"][0]["weather_risk_known"] is False
    serialized = AttractionCondition.model_validate(result["conditions"][0]).model_dump()
    assert serialized["weather_risk"] is None
    response = RiskSimulationResponse(
        trip_id=1, scenarios=100, seed=1, completion_probability=None,
        expected_disruptions=None, risk_data_status="unavailable",
        assumption="Risk simulation unavailable because risk dimensions are unknown.",
    )
    assert response.model_dump()["completion_probability"] is None
