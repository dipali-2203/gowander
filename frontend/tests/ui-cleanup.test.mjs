import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const shell = readFileSync(
  new URL("../src/components/layout/AppShell.tsx", import.meta.url),
  "utf8",
);
const planner = readFileSync(new URL("../src/routes/app/planner.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const explore = readFileSync(new URL("../src/routes/app/explore.tsx", import.meta.url), "utf8");

test("top navigation keeps theme, profile, and logout controls without notifications", () => {
  assert.doesNotMatch(shell, /aria-label="Notifications"|<Bell|import[\s\S]*\bBell\b/);
  assert.match(shell, /aria-label="Toggle theme"/);
  assert.match(shell, /aria-label="Open profile"/);
  assert.match(shell, /aria-label="Sign out"/);
});

test("sidebar trial promotion is removed without changing the navigation list", () => {
  assert.doesNotMatch(shell, /Pro trial|AI itineraries left|Renews on|>Upgrade</);
  assert.match(shell, /<NavList \/>/);
});

test("planner has no attraction preview while itinerary generation still loads the catalog", () => {
  assert.doesNotMatch(
    planner,
    /catalog\.attractions|catalogLoading|Attraction details load from the local catalog/,
  );
  assert.match(planner, /getAttractionCatalog\(destination\)/);
  assert.match(planner, /createAndOptimizeTrip\(/);
  assert.match(api, /export function getAttractionCatalog\(destination: string\)/);
  assert.match(
    api,
    /export async function createAndOptimizeTrip[\s\S]*const catalog = await getAttractionCatalog/,
  );
  assert.match(api, /\/api\/v1\/attractions\/catalog/);
});

test("Explore retains the attraction catalog and interactive map", () => {
  assert.match(explore, /getAttractionCatalog\(attractionCity\)/);
  assert.match(explore, /Attraction catalog/);
  assert.match(explore, /<AttractionMap/);
});
