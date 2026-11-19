import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const planner = readFileSync(new URL("../src/routes/app/planner.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const panel = readFileSync(new URL("../src/components/travel/TripBudgetEstimatePanel.tsx", import.meta.url), "utf8");

test("planner separates local modes from intercity fare modes", () => {
  const intercity = planner.slice(planner.indexOf("<h3 className=\"text-sm font-semibold\">Intercity transportation</h3>"));
  assert.match(planner, /Local transportation/);
  assert.match(planner, /Intercity transportation/);
  assert.match(planner, /SelectItem value="walking"/);
  assert.match(planner, /SelectItem value="public_transport"/);
  assert.match(planner, /SelectItem value="auto"/);
  assert.match(planner, /SelectItem value="rental_vehicle"/);
  assert.match(planner, /SelectItem value="private_car">Private car/);
  assert.match(planner, /Not decided/);
  assert.doesNotMatch(intercity, /SelectItem value="flight">Flights<\/SelectItem>/);
  assert.doesNotMatch(intercity, /SelectItem value="mixed">Mixed<\/SelectItem>/);
});

test("planner displays ranges, whole-group wording, and unavailable estimates", () => {
  assert.match(planner, /Indicative range/);
  assert.match(planner, /whole group/);
  assert.match(planner, /Estimate unavailable/);
  assert.match(planner, /manual amount takes priority/);
});

test("manual estimate confirmation is required before trip creation", () => {
  assert.match(api, /confirmation_required/);
  assert.match(api, /window\.confirm/);
  assert.match(api, /zero_fare_confirmed/);
  assert.match(api, /override_confirmed/);
  assert.match(api, /intercity_destination_latitude/);
});

test("complete budget shows category ranges and conservative feasibility", () => {
  assert.match(panel, /Indicative range/);
  assert.match(panel, /upper estimate/);
  assert.match(panel, /Rate basis/);
  assert.match(panel, /Amount basis/);
});
