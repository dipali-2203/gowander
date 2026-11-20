import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const itinerary = readFileSync(new URL("../src/routes/app/itinerary.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const sharedPage = readFileSync(
  new URL("../src/routes/shared.$token.tsx", import.meta.url),
  "utf8",
);
const budgetPanel = readFileSync(
  new URL("../src/components/travel/TripBudgetEstimatePanel.tsx", import.meta.url),
  "utf8",
);
const budgetPage = readFileSync(new URL("../src/routes/app/budget.tsx", import.meta.url), "utf8");

test("weather cards reflow in narrow containers and share one partial-coverage note", () => {
  const card = itinerary.slice(
    itinerary.indexOf("function WeatherForecastCard"),
    itinerary.indexOf("function advisoryLabel"),
  );
  assert.match(card, /repeat\(auto-fit, minmax\(min\(100%, 7\.5rem\), 1fr\)\)/);
  assert.doesNotMatch(card, /Forecast coverage is partial/);
  assert.match(itinerary, /grid-cols-1 gap-3 2xl:grid-cols-2/);
  assert.match(itinerary, /Forecast coverage is partial for one or more activities/);
});

test("saved itinerary actions download the current PDF and open a functional share dialog", () => {
  assert.match(itinerary, /Download PDF/);
  assert.match(itinerary, /downloadTripPdf\(selectedTripId\)/);
  assert.doesNotMatch(itinerary, /Regenerate|toast\(\"Editing mode/);
  assert.match(itinerary, /Generate share link/);
  assert.match(itinerary, /Copy link/);
  assert.match(itinerary, /Revoke link/);
  assert.match(api, /\/api\/v1\/trips\/\$\{tripId\}\/export\.pdf/);
  assert.match(api, /\/api\/v1\/trips\/\$\{tripId\}\/share-link/);
  assert.match(api, /\/api\/v1\/shared\/\$\{encodeURIComponent\(token\)\}/);
});

test("public share route is branded, read-only and does not expose private trip fields", () => {
  assert.match(sharedPage, /Shared read-only itinerary/);
  assert.match(sharedPage, /This shared itinerary is unavailable/);
  assert.match(sharedPage, /getSharedItinerary\(token\)/);
  assert.doesNotMatch(sharedPage, /preferences|owner_user_id|trip_id|attraction_id/);
  assert.doesNotMatch(sharedPage, /Accept revision|Regenerate|Edit trip/);
});

test("complete budget displays distinguish unavailable, partial, legacy and stale estimates", () => {
  assert.match(
    budgetPanel,
    /category\.status === "unavailable" \|\| typeof category\.amount !== "number"/,
  );
  assert.doesNotMatch(budgetPanel, /category\.amount\s*\?\?\s*0/);
  assert.match(budgetPanel, /available estimate · partial/);
  assert.match(budgetPanel, /Destination-only estimate/);
  assert.match(budgetPanel, /Trip budget needs refresh/);
  assert.match(budgetPanel, /budget\.within_budget === true/);
  assert.match(budgetPage, /Current complete-trip categories/);
  assert.match(budgetPage, /Legacy Destination Estimates/);
});

test("shared page uses the budget panel and backend adds a public allowlist to PDF and shared views", () => {
  const sharedApi = readFileSync(
    new URL("../../backend/app/api/shared_trips.py", import.meta.url),
    "utf8",
  );
  const pdf = readFileSync(
    new URL("../../backend/app/services/itinerary_pdf.py", import.meta.url),
    "utf8",
  );
  assert.match(sharedPage, /TripBudgetEstimatePanel/);
  assert.match(sharedPage, /estimate_is_current/);
  assert.match(sharedApi, /public_complete/);
  assert.match(sharedApi, /complete_budget_current/);
  assert.match(pdf, /Complete trip budget/);
  assert.match(pdf, /Legacy destination-only estimate/);
  assert.match(pdf, /unknown costs are not counted as zero/);
});
