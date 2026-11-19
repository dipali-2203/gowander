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
const hotelMap = readFileSync(
  new URL("../src/components/travel/LeafletHotelLocationMap.tsx", import.meta.url),
  "utf8",
);
const hotelMapLoader = readFileSync(
  new URL("../src/components/travel/HotelLocationMap.tsx", import.meta.url),
  "utf8",
);
const indiaMap = readFileSync(
  new URL("../src/components/travel/IndiaMap.tsx", import.meta.url),
  "utf8",
);
const exploreMap = readFileSync(
  new URL("../src/components/travel/LeafletAttractionMap.tsx", import.meta.url),
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

test("Hotels map uses returned hotel coordinates and catalog coordinates for scheduled attractions", () => {
  assert.match(hotelMap, /hotel\.latitude, hotel\.longitude/);
  assert.match(hotelMap, /attraction\.latitude, attraction\.longitude/);
  assert.match(page, /getAttractionCatalog\(currentTrip\.destination\)/);
  assert.match(page, /scheduledIds\.has\(attraction\.id\)/);
  assert.match(page, /attraction\.data_source !== "synthetic"/);
});

test("map validates and deduplicates coordinates, fits the viewport, and supports resetting it", () => {
  assert.match(hotelMap, /Number\.isFinite\(latitude\)/);
  assert.match(hotelMap, /latitude >= -90 &&\s+latitude <= 90/);
  assert.match(hotelMap, /longitude >= -180 &&\s+longitude <= 180/);
  assert.match(hotelMap, /seen\.has\(attraction\.id\)/);
  assert.match(hotelMap, /map\.fitBounds\(bounds/);
  assert.match(hotelMap, /aria-label="Reset map view"/);
  assert.match(hotelMap, /Map location data is unavailable/);
});

test("hotel and attraction markers are distinct and hotel popups preserve unknown fields", () => {
  assert.match(hotelMap, /fillColor: "#14b8a6"/);
  assert.match(hotelMap, /fillColor: isSavedSelection \? "#f59e0b"/);
  assert.match(hotelMap, /Price unavailable/);
  assert.match(hotelMap, /Mapped classification unavailable/);
  assert.match(hotelMap, /Recommendation score unavailable/);
  assert.match(hotelMap, /hotel\.source_url/);
  assert.match(hotelMap, /attraction\.source_url/);
  assert.match(hotelMap, /OpenStreetMap contributors/);
  assert.match(hotelMap, /Hotel distances shown in recommendations are straight-line estimates/);
});

test("map selection focuses the existing hotel card without changing stay selection behavior", () => {
  assert.match(hotelMap, /onSelectHotel\(hotel\.id\)/);
  assert.match(page, /hotelCardRefs\.get\(hotelId\)\?\.scrollIntoView/);
  assert.match(page, /selectedHotelId=\{data\.selected_accommodation\?\.hotel_id/);
  assert.match(page, /selectTripAccommodation\(selectedTripId, hotel\.id\)/);
  assert.match(page, /removeTripAccommodation\(selectedTripId\)/);
  assert.match(page, /mapKey=\{String\(selectedTripId\)\}/);
});

test("inventory-empty state keeps planned attraction mapping and no longer uses the static India map", () => {
  assert.match(page, /No sourced hotel inventory/);
  assert.match(page, /hotels=\{\[\]\}/);
  assert.doesNotMatch(page, /<IndiaMap/);
  assert.match(hotelMapLoader, /import\("\.\/LeafletHotelLocationMap"\)/);
  assert.match(indiaMap, /Stylised interactive map of India/);
  assert.match(exploreMap, /MapContainer/);
});
