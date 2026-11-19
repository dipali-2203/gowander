import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const bookmarks = readFileSync(
  new URL("../src/components/layout/BookmarksSection.tsx", import.meta.url),
  "utf8",
);
const explore = readFileSync(new URL("../src/routes/app/explore.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");

test("bookmark screen resolves OSM IDs from the cached Jaipur and Udaipur catalogs", () => {
  assert.match(bookmarks, /getAttractionCatalog\("jaipur"\)/);
  assert.match(bookmarks, /getAttractionCatalog\("udaipur"\)/);
  assert.match(bookmarks, /Promise\.allSettled/);
  assert.match(bookmarks, /bookmarkIds\.includes\(attraction\.id\)/);
  assert.match(api, /attractionCatalogCache/);
});

test("destination bookmarks keep their existing display and unresolved POIs hide raw IDs", () => {
  assert.match(
    bookmarks,
    /destination\?\.name \?\? poi\?\.name \?\? "Attraction details unavailable"/,
  );
  assert.match(bookmarks, /destination\.state/);
  assert.match(bookmarks, /destination\.image/);
  assert.doesNotMatch(bookmarks, /destination\?\.name \?\? id/);
});

test("resolved attraction bookmark links to its selected attraction in Explore", () => {
  assert.match(bookmarks, /destination=\$\{encodeURIComponent\(poi\.city\.toLowerCase\(\)\)\}/);
  assert.match(bookmarks, /attractionId=\$\{encodeURIComponent\(id\)\}/);
  assert.match(explore, /search\["attractionId"\]/);
  assert.match(explore, /setAttractionCity\(requestedDestination\)/);
  assert.match(explore, /selectPoi\(requestedAttractionId\)/);
});

test("bookmark removal remains available for resolved and unresolved entries", () => {
  assert.match(bookmarks, /await removeBookmark\(id\)/);
  assert.match(bookmarks, /disabled=\{removing === id\}/);
  assert.match(bookmarks, /Could not load bookmarks/);
  assert.match(bookmarks, /Some attraction details could not be loaded/);
});
