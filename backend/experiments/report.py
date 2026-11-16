"""Render a concise, evidence-backed Markdown report from an experiment JSON file."""

import argparse
import json
from pathlib import Path


def render(data: dict) -> str:
    summary = data["summary"]
    return f"""# ADAPT-Trip baseline comparison

## Reproducibility

- Dataset: `{data['dataset']}`
- Routing: `{data['routing']}`
- Random seeds: `{', '.join(map(str, data['seeds']))}`
- Runs: `{len(data['records'])}`

## Measured results

| Metric | Greedy baseline | NSGA-II |
| --- | ---: | ---: |
| Mean runtime (ms) | {summary['greedy_runtime_ms_mean']} | {summary['nsga2_runtime_ms_mean']} |
| Mean satisfaction | {summary['greedy_satisfaction_mean']} | — |
| Mean Pareto alternatives | — | {summary['nsga2_alternatives_mean']} |

Simulated annealing mean runtime: **{summary['annealing_runtime_ms_mean']} ms**. Simulated annealing mean satisfaction: **{summary['annealing_satisfaction_mean']}**.

## Interpretation

The greedy planner is the fast feasibility baseline. NSGA-II takes longer because it evaluates a population over multiple generations and returns several trade-off alternatives. These values describe only the bundled synthetic Jaipur catalog with Haversine travel estimates; they do not establish real-world routing, demand, weather, or crowding performance.

## Method limits

NSGA-II currently optimizes attraction-set proxies, then decodes each selected set through the greedy feasibility planner. Future experiments should use independently sourced attraction data, larger scenarios, repeated disruption trials, and formal statistical tests before drawing comparative claims.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(data), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
