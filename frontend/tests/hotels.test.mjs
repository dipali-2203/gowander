import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/routes/app/hotels.tsx", import.meta.url), "utf8");
const card = readFileSync(
  new URL("../src/components/travel/HotelCard.tsx", import.meta.url),
  "utf8",
);
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const budget = readFileSync(new URL("../src/routes/app/budget.tsx", import.meta.url), "utf8");
const tripDetails = readFileSync(
  new URL("../src/routes/app/trips.$tripId.tsx", import.meta.url),
  "utf8",
);

test("hotel page uses saved trip recommendations rather than sample hotel cards", () => {
  assert.match(page, /getHotelRecommendations/);
  assert.match(page, /getUserTrips/);
  assert.match(page, /Select saved trip for hotel recommendations/);
  assert.match(page, /No sourced hotel inventory/);
  assert.doesNotMatch(page, /@\/data\/hotels/);
  assert.equal(existsSync(new URL("../src/data/hotels.ts", import.meta.url)), false);
});

test("hotel details and cards keep absent prices, ratings, amenities and bookings unknown", () => {
  assert.match(card, /Price unavailable/);
  assert.match(card, /Guest rating unavailable/);
  assert.match(card, /Amenities unavailable/);
  assert.match(page, /booking availability/);
  assert.match(page, /mapped hotel stars unavailable/i);
  assert.match(page, /straight-line distance/);
  assert.match(page, /OpenStreetMap/);
});

test("hotel filters, view dialog, trip selection and removal use live recommendation fields", () => {
  for (const filter of ["All", "Budget", "Luxury", "Family", "Business", "Couples"])
    assert.ok(page.includes(`"${filter}"`));
  assert.match(card, /onView\(hotel\)/);
  assert.match(page, /selectTripAccommodation\(selectedTripId, hotel\.id\)/);
  assert.match(page, /removeTripAccommodation\(selectedTripId\)/);
  assert.match(page, /Why this match\?/);
  assert.match(page, /Score components/);
});

test("trip selection and current estimate are shown on itinerary, saved trip and budget views", () => {
  assert.match(api, /\/api\/v1\/trips\/\$\{tripId\}\/accommodation/);
  assert.match(tripDetails, /Change or remove stay/);
  assert.match(budget, /Complete Trip Cost/);
  assert.match(budget, /selected_accommodation\.name/);
});
