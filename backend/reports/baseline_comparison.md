# ADAPT-Trip baseline comparison

## Reproducibility

- Dataset: `synthetic_jaipur_catalog_v1`
- Routing: `haversine_estimate`
- Random seeds: `7, 19, 42, 73, 101`
- Runs: `5`

## Measured results

| Metric | Greedy baseline | NSGA-II |
| --- | ---: | ---: |
| Mean runtime (ms) | 0.093 | 886.939 |
| Mean satisfaction | 0.8 | — |
| Mean Pareto alternatives | — | 3 |

Simulated annealing mean runtime: **3.333 ms**. Simulated annealing mean satisfaction: **0.8**.

## Interpretation

The greedy planner is the fast feasibility baseline. NSGA-II takes longer because it evaluates a population over multiple generations and returns several trade-off alternatives. These values describe only the bundled synthetic Jaipur catalog with Haversine travel estimates; they do not establish real-world routing, demand, weather, or crowding performance.

## Method limits

NSGA-II currently optimizes attraction-set proxies, then decodes each selected set through the greedy feasibility planner. Future experiments should use independently sourced attraction data, larger scenarios, repeated disruption trials, and formal statistical tests before drawing comparative claims.
