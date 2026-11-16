"""Condition-provider boundary that separates estimated from live observations."""

from datetime import datetime, timezone

from app.schemas import AttractionInput


def estimated_conditions(attractions: list[AttractionInput]) -> dict:
    return {
        "source": "estimated",
        "observed_at": datetime.now(timezone.utc),
        "conditions": [
            {"attraction_id": item.id, "weather_risk": item.weather_risk, "crowd_risk": item.crowd_risk, "availability_risk": item.availability_risk}
            for item in attractions
        ],
    }
