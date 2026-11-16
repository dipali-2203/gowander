"""Run deterministic disruption-replanning scenarios against the synthetic catalog."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from app.data.catalog import SYNTHETIC_CATALOG, SYNTHETIC_START_LOCATIONS
from app.schemas import Disruption, Preferences
from app.services.disruptions import apply_disruptions
from app.services.planner import generate_greedy_itinerary
from app.services.routing import build_travel_time_matrix


SCENARIOS = [
    Disruption(kind="rainfall", severity=0.6),
    Disruption(kind="traffic", severity=0.6),
    Disruption(kind="crowding", severity=0.6),
    Disruption(kind="closure", severity=1.0, affected_attraction_ids=["jaipur-amber"]),
]


def run() -> dict:
    attractions = SYNTHETIC_CATALOG["jaipur"]
    start = SYNTHETIC_START_LOCATIONS["jaipur"]
    matrix = build_travel_time_matrix(start, attractions)
    preferences = Preferences(interests={"history": 1, "food": 0.8, "sightseeing": 0.7})
    records = []
    for disruption in SCENARIOS:
        updated, adjusted_matrix, closed, applied = apply_disruptions(attractions, [disruption], matrix)
        eligible = [item for item in updated if item.id not in closed]
        indices = [0, *[index + 1 for index, item in enumerate(updated) if item.id not in closed]]
        submatrix = [[adjusted_matrix[i][j] for j in indices] for i in indices]
        started = perf_counter()
        result = generate_greedy_itinerary(
            attractions=eligible, preferences=preferences, start_latitude=start[0], start_longitude=start[1],
            budget=5_000, available_minutes=720, travel_matrix=submatrix,
        )
        records.append({
            "scenario": applied[0], "excluded_attractions": sorted(closed),
            "runtime_ms": round((perf_counter() - started) * 1_000, 3),
            "feasible": result["feasible"], "stops": len(result["stops"]),
            "cost": result["total_cost"], "risk_score": result["risk_score"],
        })
    return {"dataset": "synthetic_jaipur_catalog_v1", "routing": "haversine_estimate", "records": records}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(run(), indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
