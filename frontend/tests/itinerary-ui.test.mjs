import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/routes/app/itinerary.tsx", import.meta.url), "utf8");
const savedTripSource = readFileSync(
  new URL("../src/routes/app/trips.$tripId.tsx", import.meta.url),
  "utf8",
);

test("advanced itinerary tools are grouped in a native collapsed-by-default disclosure", () => {
  const start = source.indexOf('<details className="surface p-4">');
  assert.notEqual(start, -1);
  const end = source.indexOf("</details>", start);
  assert.notEqual(end, -1);
  const advanced = source.slice(start, end);
  assert.doesNotMatch(source.slice(start, source.indexOf(">", start)), /\bopen\b/);
  for (const section of [
    "Advanced Optimization Insights",
    "Reliability estimate",
    "Planning conditions",
    "Pareto",
    "Single-day simulated annealing",
    "What-if replanning",
    "Optimizer assumptions and technical warnings",
  ]) {
    assert.ok(advanced.includes(section), `missing advanced section: ${section}`);
  }
  assert.ok(savedTripSource.includes("Advanced Optimization Insights"));
  assert.ok(savedTripSource.includes("Saved single-day optimization alternatives"));
  assert.ok(savedTripSource.includes("stop.wait_reason"));
});

test("traveler budget copy identifies destination scope and unknown fees", () => {
  assert.ok(source.includes("Estimated destination expenses"));
  assert.ok(source.includes("travel and unknown attraction fees are excluded."));
  assert.ok(source.includes("zero-cost placeholder"));
  assert.ok(source.includes("budgetEstimate.exclusions.map"));
  assert.ok(source.includes("loadConditions(generated.trip_id, plannedAttractions)"));
  assert.ok(savedTripSource.includes("Estimated destination expenses"));
  assert.ok(savedTripSource.includes("internal zero-cost placeholders do not mean entry is free"));
  assert.ok(savedTripSource.includes("itinerary.budget_estimate.exclusions.map"));
});

test("single-day optimizer results are explicitly distinguished from the multi-day plan", () => {
  assert.ok(source.includes("Single-day optimization alternatives (Pareto)"));
  assert.ok(source.includes("Single-day simulated annealing comparison"));
  assert.match(source, /do not replace this multi-day\s+itinerary/);
});

test("scheduled waits include an explanation when present", () => {
  assert.ok(source.includes("stop.wait_reason"));
  assert.ok(source.includes("min waiting"));
});
