import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ui = readFileSync(new URL("../src/routes/app/itinerary.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");

test("real forecast proposals are explicitly separate from simulated scenarios", () => {
  assert.match(ui, /Forecast-based proposal/);
  assert.match(ui, /Simulated what-if inputs use synthetic estimates/);
  assert.match(ui, /proposeWeatherReplan\(selectedTripId, dayNumber\)/);
});

test("unavailable forecast data is disclosed, and revisions require explicit acceptance", () => {
  assert.match(ui, /Weather information unavailable/);
  assert.match(ui, /Accept revision/);
  assert.match(ui, /Keep current itinerary/);
  assert.doesNotMatch(
    ui,
    /weather_assessment\["known"\]|Weather advisory:|Weather data unavailable"\s*:/,
  );
  assert.match(api, /replan\/weather\/accept/);
  assert.match(api, /replan\/weather\/reject/);
});

test("forecast readings are human-readable and omit unavailable values", () => {
  assert.match(ui, /WeatherForecastCard/);
  assert.match(ui, /values\.precipitation_probability/);
  assert.match(ui, /values\.apparent_temperature/);
  assert.match(ui, /values\.wind_speed_10m/);
  assert.match(ui, /value === undefined \|\| value === null \? null/);
  assert.match(ui, /formatForecastTimestamp/);
  assert.match(ui, /item\.risk\.condition/);
});

test("complete, partial, and unavailable coverage use distinct no-change explanations", () => {
  assert.match(
    ui,
    /Weather conditions look suitable for your scheduled outdoor activities\. No changes are currently recommended\./,
  );
  assert.match(ui, /No changes are currently recommended based on the available forecast values/);
  assert.match(ui, /Forecast coverage is partial for one or more activities/);
  assert.match(ui, /conditions can change/i);
});

test("normal and advanced itinerary views never render weather response JSON", () => {
  assert.doesNotMatch(ui, /JSON\.stringify\(weatherProposal\.weather_summary/);
  assert.doesNotMatch(ui, /<pre[^>]*>\s*\{JSON\.stringify/);
  assert.match(ui, /Forecast assessment coverage/);
});

test("weather advisory summaries preserve reason, forecast time and alternative status", () => {
  assert.match(ui, /weatherProposal\.weather_summary\.map/);
  assert.match(ui, /advisoryLabel\(advisory\.type\)/);
  assert.match(ui, /change\.weather_risk\?\.forecast_time/);
  assert.match(ui, /Alternative found:/);
  assert.match(ui, /No suitable alternative was found/);
  assert.match(ui, /Original plan/);
  assert.match(ui, /Proposed plan/);
});

test("completed activity state is saved against the itinerary revision", () => {
  assert.match(ui, /saveCompletedActivities\(selectedTripId, next, itineraryRevision\)/);
  assert.match(api, /completed_attraction_ids: completedAttractionIds/);
});
