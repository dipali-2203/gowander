import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ui = readFileSync(new URL("../src/routes/app/assistant.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");

test("assistant sends current-session history and selected trip context to backend", () => {
  assert.match(ui, /sendAssistantMessage\(\{/);
  assert.match(ui, /trip_id:\s*selectedTripId/);
  assert.match(ui, /conversation_history:\s*history/);
  assert.match(api, /\/api\/v1\/assistant\/chat/);
});

test("assistant exposes loading and recoverable error states without mock replies", () => {
  assert.match(ui, /setTyping\(true\)/);
  assert.match(ui, /setTyping\(false\)/);
  assert.match(ui, /role="alert"/);
  assert.match(ui, /try again/);
  assert.doesNotMatch(ui, /setTimeout\(/);
  assert.doesNotMatch(ui, /const replies:/);
});

test("assistant keeps provider credentials private and only applies explicit proposal actions", () => {
  assert.doesNotMatch(ui, /GEMINI_API_KEY|generativelanguage\.googleapis\.com/);
  assert.doesNotMatch(ui, /regenerateTrip\(|acceptWeatherReplan\(|selectTripAccommodation\(/);
  assert.match(api, /acceptAssistantProposal/);
  assert.match(api, /rejectAssistantProposal/);
  assert.match(ui, /Proposed itinerary change/);
  assert.match(ui, /Accept changes/);
  assert.match(ui, /No changes were made/);
  assert.match(ui, /proposal\.validation\.valid/);
  assert.match(ui, /getUserTrips\(\)/);
});
