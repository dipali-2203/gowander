import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const panel = source("../src/components/travel/TripBudgetEstimatePanel.tsx");
const planner = source("../src/routes/app/planner.tsx");
const savedTrip = source("../src/routes/app/trips.$tripId.tsx");
const budgetDashboard = source("../src/routes/app/budget.tsx");
const api = source("../src/lib/api.ts");
const sharedPage = source("../src/routes/shared.$token.tsx");
const pdf = source("../../backend/app/services/itinerary_pdf.py");
const sharedApi = source("../../backend/app/api/shared_trips.py");

test("budget panel presents verified, estimated, unresolved, range, and provenance fields", () => {
  assert.match(panel, /Verified fees:/);
  assert.match(panel, /Estimated fees:/);
  assert.match(panel, /Unresolved amount:/);
  assert.match(panel, /estimate_config_version/);
  assert.match(panel, /Fee provenance:/);
  assert.match(panel, /Fee range: lower/);
  assert.match(panel, /representative/);
  assert.match(panel, /upper/);
  assert.match(panel, /Representative estimate over budget/);
  assert.match(panel, /Upper-range estimate over budget/);
  assert.match(panel, /available estimate · partial/);
  assert.doesNotMatch(panel, /known subtotal`\s*:\s*category.amount/);
});

test("planner sends automatic, manual, and disabled miscellaneous modes without re-estimating", () => {
  assert.match(planner, /Automatic estimate/);
  assert.match(planner, /Manual amount/);
  assert.match(planner, /No allowance/);
  assert.match(planner, /representative estimate is 10%/);
  assert.match(planner, /5–15% range/);
  assert.match(planner, /other six budget categories/);
  assert.match(planner, /miscellaneousBudgetMode: form.miscellaneousMode/);
  assert.match(api, /miscellaneous_budget_mode: input.miscellaneousBudgetMode/);
  assert.match(api, /miscellaneousBudgetMode: MiscellaneousBudgetMode/);
});

test("saved trips restore the selected mode and submit it unchanged when edited", () => {
  assert.match(savedTrip, /saved.planning_options.miscellaneous_budget_mode/);
  assert.match(
    savedTrip,
    /saved.planning_options.miscellaneous_budget > 0 \? "manual" : "automatic"/,
  );
  assert.match(savedTrip, /miscellaneous_budget_mode: form.miscellaneousMode/);
  assert.match(savedTrip, /miscellaneousMode === "manual" \? miscellaneousAmount : 0/);
});

test("dashboard separates original unknown fees from estimated and unresolved counts", () => {
  assert.match(budgetDashboard, /originalUnknownCount/);
  assert.match(budgetDashboard, /estimatedCount/);
  assert.match(budgetDashboard, /unresolvedCount/);
  assert.match(budgetDashboard, /same verified and versioned estimates/);
  assert.match(budgetDashboard, /optimizer's activity costs remain separate/);
  assert.match(budgetDashboard, /Daily attraction fee estimates/);
  assert.match(budgetDashboard, /Fee estimate unavailable/);
});

test("shared itinerary reuses the same budget panel and transportation fields remain present", () => {
  assert.match(sharedPage, /TripBudgetEstimatePanel/);
  assert.match(planner, /Intercity transportation/);
  assert.match(planner, /getTransportationEstimate/);
  assert.match(pdf, /available estimate \(partial\)/);
  assert.match(sharedApi, /estimated_amount/);
  assert.match(sharedApi, /unresolved_count/);
  assert.match(sharedApi, /daily_attraction_fees/);
  assert.match(api, /daily_attraction_fees\?: DailyAttractionFees\[\]/);
  assert.match(pdf, /Daily attraction fee estimates/);
});
