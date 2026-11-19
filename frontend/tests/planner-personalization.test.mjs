import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { boostBookmarkedAttractions } from "../src/lib/personalization.ts";

const planner = readFileSync(new URL("../src/routes/app/planner.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const personalization = readFileSync(
  new URL("../src/lib/personalization.ts", import.meta.url),
  "utf8",
);

test("saved planner defaults respect fields the traveler already edited", () => {
  for (const field of ["picks", "days", "budget", "transport", "pace", "hotelBudget"]) {
    assert.match(planner, new RegExp(`editedFields\\.current\\.has\\("${field}"\\)`));
    assert.match(planner, new RegExp(`editedFields\\.current\\.add\\("${field}"\\)`));
  }
  assert.match(planner, /getTravelPreferences\(\)/);
  assert.match(planner, /\.catch\(\(\) => \{/);
});

test("all supported saved preference defaults have explicit planner mappings", () => {
  assert.match(planner, /preferences\.interests/);
  assert.match(planner, /preferred_trip_duration_days/);
  assert.match(planner, /daily_budget_inr/);
  assert.match(planner, /preferences\.transportation/);
  assert.match(planner, /preferences\.travel_pace/);
  assert.match(planner, /style\.toLowerCase\(\) === "slow travel"/);
  assert.match(planner, /accommodationDefaults/);
  assert.match(planner, /hostel: "low"/);
  assert.match(planner, /"budget hotel": "low"/);
});

test("bookmarks softly boost exact catalog identities across all planner optimizer calls", () => {
  assert.match(api, /getAttractionCatalog\(input\.destination\)/);
  assert.match(api, /const bookmarks = await getBookmarks\(\)/);
  assert.match(api, /catch \{[\s\S]*Personalization is optional/);
  assert.match(api, /attractions,\s*algorithm: "greedy"/);
  assert.match(api, /attractions,\s*algorithm: "nsga2"/);
  assert.match(api, /attractions,\s*algorithm: "simulated_annealing"/);
  assert.match(personalization, /bookmarkedIds\.has\(attraction\.id\)/);
  assert.match(personalization, /Math\.min\(1, attraction\.preference_score \+ amount\)/);
  assert.match(
    personalization,
    /if \(bookmarkedIds\.size === 0 \|\| amount <= 0\) return attractions/,
  );
});

test("unsupported preference representations are not translated into invented scores or budgets", () => {
  assert.doesNotMatch(planner, /budget_preference\s*:/);
  assert.doesNotMatch(personalization, /styles/);
  assert.match(planner, /preferences\.styles\.some/);
});

test("bookmark boost matches stable IDs, is capped, and leaves other candidates eligible", () => {
  const candidates = [
    { id: "osm:node:1", preference_score: 0.5, priority_score: 0.7 },
    { id: "osm:way:2", preference_score: 0.95, priority_score: 1 },
  ];
  const adjusted = boostBookmarkedAttractions(candidates, new Set(["osm:node:1", "osm:node:999"]));

  assert.equal(adjusted.length, candidates.length);
  assert.equal(adjusted[0].preference_score, 0.62);
  assert.equal(adjusted[0].priority_score, 0.82);
  assert.equal(adjusted[1], candidates[1]);
});

test("an empty bookmark set preserves the existing candidate list and scores", () => {
  const candidates = [{ id: "osm:node:1", preference_score: 0.5 }];
  assert.equal(boostBookmarkedAttractions(candidates, new Set()), candidates);
});
