import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ui = readFileSync(new URL("../src/routes/app/assistant.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");

test("assistant sends current-session history and selected trip context to backend", () => {
  assert.match(ui, /sendAssistantMessage\(\{/);
  assert.match(ui, /trip_id:\s*request\.tripId/);
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

test("assistant retries the preserved message with the same request ID and blocks duplicates while pending", () => {
  assert.match(ui, /requestInFlightRef\.current\) return/);
  assert.match(ui, /Retry message/);
  assert.match(ui, /send\(retryableMessage\.message, retryableMessage\)/);
  assert.match(ui, /request_id:\s*request\.requestId/);
  assert.match(ui, /retryableMessage !== null/);
  assert.match(api, /request_id: string/);
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

test("preference proposals render readable interest, tolerance, and transport before/after values", () => {
  assert.match(ui, /interest weight/);
  assert.match(ui, /Walking tolerance/);
  assert.match(ui, /Crowd tolerance/);
  assert.match(ui, /Risk tolerance/);
  assert.match(ui, /Transportation mode/);
  assert.match(ui, /Math\.round\(value \* 100\)/);
  assert.match(ui, /changeLabel\(change\.field\).*changeValue\(change\.field, change\.before\)/s);
});

test("attraction proposals show catalog details without turning unknown values into facts", () => {
  assert.match(ui, /Attraction added/);
  assert.match(ui, /Attraction removed/);
  assert.match(ui, /Attraction replaced/);
  assert.match(ui, /change\.cost_known && typeof change\.fee === "number"/);
  assert.match(ui, /change\.visit_duration_known && typeof change\.visit_minutes === "number"/);
  assert.match(ui, /change\.opening_hours \|\| "Unavailable"/);
  assert.match(ui, /change\.provider_name \|\| change\.data_source/);
  assert.match(ui, /change\.attribution/);
  assert.match(ui, /\^https\?:\\\/\\\//);
  assert.match(ui, /Accept changes/);
  assert.match(ui, /Reject/);
});
