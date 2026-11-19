import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const explore = readFileSync(new URL("../src/routes/app/explore.tsx", import.meta.url), "utf8");
const map = readFileSync(
  new URL("../src/components/travel/LeafletAttractionMap.tsx", import.meta.url),
  "utf8",
);
const mapLoader = readFileSync(
  new URL("../src/components/travel/AttractionMap.tsx", import.meta.url),
  "utf8",
);
const indiaMap = readFileSync(
  new URL("../src/components/travel/IndiaMap.tsx", import.meta.url),
  "utf8",
);

test("destination map uses the loaded Jaipur and Udaipur catalog coordinates", () => {
  assert.match(explore, /getAttractionCatalog\(attractionCity\)/);
  assert.match(explore, /city=\{attractionCity\}/);
  assert.match(explore, /attractions=\{visiblePois\}/);
  assert.match(map, /center=\{\[place\.latitude, place\.longitude\]\}/);
  assert.match(map, /jaipur: \[26\.9124, 75\.7873\]/);
  assert.match(map, /udaipur: \[24\.5854, 73\.7125\]/);
  assert.match(map, /map\.fitBounds\(bounds/);
  assert.match(map, /scrollWheelZoom/);
  assert.match(map, /Reset map view/);
  assert.match(map, /Map tiles are temporarily unavailable/);
});

test("search, categories, featured selection and visible markers share the same attractions", () => {
  assert.match(explore, /const visiblePois =/);
  assert.match(explore, /poiCategory === "All"/);
  assert.match(explore, /place\.name\.toLowerCase\(\)\.includes\(q\)/);
  assert.match(explore, /attractions=\{visiblePois\}/);
  assert.match(explore, /visiblePois\.map\(\(place\)/);
  assert.match(explore, /const count =/);
});

test("map markers select catalog cards and cards focus their corresponding marker", () => {
  assert.match(map, /eventHandlers=\{\{ click: \(\) => onSelect\(place\.id\) \}\}/);
  assert.match(map, /markers\.current\[selected\.id\]\?\.openPopup\(\)/);
  assert.match(explore, /onClick=\{\(\) => selectPoi\(place\.id\)\}/);
  assert.match(explore, /poiCardRefs\.get\(id\)\?\.scrollIntoView/);
  assert.match(explore, /selectedPoiId === place\.id/);
});

test("map preserves unknown values, source links, dataset details, and attribution", () => {
  assert.match(map, /place\.cost_known \?[^:]+: "Unknown"/);
  assert.match(map, /place\.visit_duration_known \?[^:]+: "Unknown"/);
  assert.match(map, /place\.opening_window_known \?[^:]+: "Unknown"/);
  assert.match(map, /place\.source_dataset \?\? dataset/);
  assert.match(map, /Open OSM source record/);
  assert.match(map, /openstreetmap\.org\/copyright/);
  assert.match(explore, /without valid coordinates remain in the list/);
});

test("Leaflet is loaded only in the browser and the existing India map is preserved", () => {
  assert.match(mapLoader, /import\("\.\/LeafletAttractionMap"\)/);
  assert.match(explore, /<IndiaMap active=\{active\?\.id \?\? null\} onSelect=\{setActive\}/);
  assert.doesNotMatch(indiaMap, /Leaflet|leaflet/);
});
