"""Deterministic disruption transformations for scenario-based replanning."""

from math import ceil

from app.schemas import AttractionInput, Disruption
from app.services.routing import TravelMatrix


def apply_disruptions(
    attractions: list[AttractionInput], disruptions: list[Disruption], matrix: TravelMatrix,
) -> tuple[list[AttractionInput], TravelMatrix, set[str], list[str]]:
    updated = {item.id: item for item in attractions}
    closed: set[str] = set()
    traffic_multiplier = 1.0
    applied: list[str] = []
    for disruption in disruptions:
        targets = disruption.affected_attraction_ids or list(updated)
        if disruption.kind == "closure":
            closed.update(targets)
        elif disruption.kind == "traffic":
            traffic_multiplier = max(traffic_multiplier, 1 + disruption.severity)
        else:
            for attraction_id in targets:
                item = updated.get(attraction_id)
                if item is None:
                    continue
                field = "weather_risk" if disruption.kind == "rainfall" else "crowd_risk"
                key = "weather" if field == "weather_risk" else "crowd"
                metadata = {**item.risk_metadata, key: {"source": "scenario", "observed_at": None, "verified": False, "assumption": f"scenario severity {disruption.severity:.2f}"}}
                updated[attraction_id] = item.model_copy(update={
                    field: min(1.0, getattr(item, field) + disruption.severity),
                    f"{field}_known": True,
                    "risk_metadata": metadata,
                })
        applied.append(f"{disruption.kind} (severity {disruption.severity:.2f})")
    adjusted = [[None if value is None else ceil(value * traffic_multiplier) for value in row] for row in matrix]
    return list(updated.values()), adjusted, closed, applied
