"""Run the synthetic Jaipur baseline comparison with fixed seeds.

Example:
    python -m experiments.run --output reports/baseline_comparison.json
"""

import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from app.data.catalog import SYNTHETIC_CATALOG
from app.schemas import Preferences
from app.services.nsga2 import generate_nsga2_alternatives
from app.services.annealing import generate_annealed_itinerary
from app.services.planner import generate_greedy_itinerary
from app.services.routing import build_travel_time_matrix


def json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def run_experiment(seeds: list[int]) -> dict:
    """Compare greedy with NSGA-II using the same inputs and fixed seeds."""
    attractions = SYNTHETIC_CATALOG["jaipur"]
    preferences = Preferences(interests={"history": 1.0, "food": 0.8, "sightseeing": 0.7})
    start = (26.9124, 75.7873)
    budget = 5_000
    minutes = 720
    matrix = build_travel_time_matrix(start, attractions)
    records = []

    for seed in seeds:
        greedy_started = perf_counter()
        greedy = generate_greedy_itinerary(
            attractions=attractions, preferences=preferences, start_latitude=start[0],
            start_longitude=start[1], budget=budget, available_minutes=minutes,
            travel_matrix=matrix,
        )
        greedy_runtime_ms = (perf_counter() - greedy_started) * 1_000

        nsga_started = perf_counter()
        alternatives = generate_nsga2_alternatives(
            attractions=attractions, preferences=preferences, start_latitude=start[0],
            start_longitude=start[1], budget=budget, available_minutes=minutes,
            travel_matrix=matrix, seed=seed,
        )
        nsga_runtime_ms = (perf_counter() - nsga_started) * 1_000
        anneal_started = perf_counter()
        annealed = generate_annealed_itinerary(
            attractions, preferences, start[0], start[1], budget, minutes, seed,
        )
        anneal_runtime_ms = (perf_counter() - anneal_started) * 1_000
        records.append({
            "seed": seed,
            "greedy": {**greedy, "runtime_ms": round(greedy_runtime_ms, 3)},
            "nsga2": {
                "runtime_ms": round(nsga_runtime_ms, 3),
                "alternative_count": len(alternatives),
                "alternatives": alternatives,
            },
            "simulated_annealing": {**annealed, "runtime_ms": round(anneal_runtime_ms, 3)},
        })

    return {
        "dataset": "synthetic_jaipur_catalog_v1",
        "routing": "haversine_estimate",
        "seeds": seeds,
        "records": records,
        "summary": {
            "greedy_runtime_ms_mean": round(mean(item["greedy"]["runtime_ms"] for item in records), 3),
            "greedy_satisfaction_mean": round(mean(item["greedy"]["satisfaction"] for item in records), 3),
            "nsga2_runtime_ms_mean": round(mean(item["nsga2"]["runtime_ms"] for item in records), 3),
            "nsga2_alternatives_mean": round(mean(item["nsga2"]["alternative_count"] for item in records), 3),
            "annealing_runtime_ms_mean": round(mean(item["simulated_annealing"]["runtime_ms"] for item in records), 3),
            "annealing_satisfaction_mean": round(mean(item["simulated_annealing"]["satisfaction"] for item in records), 3),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", nargs="+", type=int, default=[7, 19, 42, 73, 101])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_experiment(args.seeds)
    rendered = json.dumps(result, indent=2, default=json_default)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
