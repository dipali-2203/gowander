from app.schemas import AttractionInput
from app.services.conditions import estimated_conditions


def test_estimated_conditions_identify_their_source():
    result = estimated_conditions([AttractionInput(id="a", name="A", category="history", latitude=0, longitude=0, visit_minutes=30, preference_score=0.5)])
    assert result["source"] == "estimated"
    assert result["conditions"][0]["attraction_id"] == "a"
