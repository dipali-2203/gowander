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
    "Pareto",
    "Single-day simulated annealing",
    "What-if replanning",
    "Optimizer assumptions and technical warnings",
  ]) {
    assert.ok(advanced.includes(section), `missing advanced section: ${section}`);
  }
  assert.doesNotMatch(source, /Planning conditions|inspectConditions|conditions\.conditions/);
  assert.doesNotMatch(source, /Forecast for scheduled activities|weatherSummary: day\.stops/);
  assert.match(source, /WeatherForecastCard/);
  assert.ok(savedTripSource.includes("Advanced Optimization Insights"));
  assert.ok(savedTripSource.includes("Saved single-day optimization alternatives"));
  assert.ok(savedTripSource.includes("stop.wait_reason"));
});

test("itinerary uses the shared budget panel and never treats unknown fees as free", () => {
  assert.ok(source.includes("TripBudgetEstimatePanel"));
  assert.ok(source.includes("Budget estimate unavailable"));
  assert.ok(source.includes("Unknown activity fees are"));
  assert.ok(source.includes("riskDetailsLabel("));
  assert.ok(savedTripSource.includes("TripBudgetEstimatePanel"));
  assert.ok(savedTripSource.includes("completeBudgetCurrent={trip.complete_budget_current}"));
  assert.ok(savedTripSource.includes("estimateIsCurrent={!trip.itinerary_stale}"));
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

test("accepted and rejected weather proposals clear their pending UI state", () => {
  assert.match(
    source,
    /resolvedWeatherProposalIds\.current\.add\(weatherProposal\.proposal_id\);\s*setWeatherProposal\(null\);\s*toast\.success\("Itinerary updated based on the weather forecast\."\)/,
  );
  assert.match(
    source,
    /await rejectWeatherReplan\(selectedTripId, weatherProposal\);\s*resolvedWeatherProposalIds\.current\.add\(weatherProposal\.proposal_id\);\s*setWeatherProposal\(null\)/,
  );
  assert.match(
    source,
    /restorePendingWeatherProposal\(saved\.pending_itinerary_revision \?\? null, saved\.id\)/,
  );
  assert.match(
    source,
    /proposal\.base_revision < \(itineraryRevisionsByTrip\.current\.get\(tripId\) \?\? 0\)/,
  );
  assert.match(
    source,
    /if \(\s*saved\.itinerary_revision <\s*\(itineraryRevisionsByTrip\.current\.get\(saved\.id\) \?\? 0\)\s*\)\s*return/,
  );
});

test("weather proposals stay in the proposal panel, not in daily activity rows", () => {
  assert.match(source, /\{weatherProposal \? \([\s\S]*?Forecast-based proposal/);
  const rowMappingStart = source.indexOf("const generatedDay = generated.days.map");
  const rowMappingEnd = source.indexOf("const budgetEstimate =", rowMappingStart);
  const dailyRows = source.slice(rowMappingStart, rowMappingEnd);
  assert.doesNotMatch(
    dailyRows,
    /weather_assessment|WeatherForecastCard|Weather advisory|Weather data unavailable/,
  );
  assert.match(source, /weatherProposal\.weather_summary\.map\(\(item\) => \(/);
  assert.match(source, /restorePendingWeatherProposal\(proposal, selectedTripId\)/);
});

test("all four what-if controls remain simulated and available", () => {
  assert.match(source, /\["rainfall", "traffic", "crowding", "closure"\]/);
  assert.match(
    source,
    /Simulated what-if inputs use synthetic estimates and are not actual forecasts\./,
  );
  assert.match(source, /replanScenario\(/);
});
