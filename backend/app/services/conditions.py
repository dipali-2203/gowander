"""Condition-provider boundary that separates estimated from live observations."""

from datetime import datetime, timezone

from app.schemas import AttractionInput
from app.services.planner import risk_data_status


def estimated_conditions(attractions: list[AttractionInput]) -> dict:
    return {
        "source": "estimated",
        "observed_at": datetime.now(timezone.utc),
        "conditions": [
            {"attraction_id": item.id,
             "weather_risk": item.weather_risk if item.weather_risk_known else None,
             "crowd_risk": item.crowd_risk if item.crowd_risk_known else None,
             "availability_risk": item.availability_risk if item.availability_risk_known else None,
             "weather_risk_known": item.weather_risk_known,
             "crowd_risk_known": item.crowd_risk_known,
             "availability_risk_known": item.availability_risk_known,
             "risk_data_status": risk_data_status([item]),
             "risk_metadata": item.risk_metadata}
            for item in attractions
        ],
    }
