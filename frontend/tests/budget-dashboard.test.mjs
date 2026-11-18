import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { budgetStatus, buildBudgetDashboard } from "../src/lib/budget-dashboard.mjs";

const budgetPage = readFileSync(new URL("../src/routes/app/budget.tsx", import.meta.url), "utf8");

const trip = (
  id,
  { budget = 10_000, cost = 8_500, days = 2, categories, unknownFees = 0 } = {},
) => ({
  id,
  budget,
  destination: id === 1 ? "Jaipur" : "Udaipur",
  start_date: "2026-12-01",
  end_date: `2026-12-0${days}`,
  latest_itinerary:
    cost === null
      ? null
      : {
          budget_estimate: {
            total_estimated: cost,
            unknown_attraction_fee_count: unknownFees,
            categories: categories ?? [
              { key: "accommodation", amount: 2000 },
              { key: "transportation", amount: 1000 },
              { key: "meals", amount: 3000 },
              { key: "attractions", amount: 1500 },
              { key: "miscellaneous", amount: 1000 },
            ],
          },
          days: Array.from({ length: days }, (_, index) => ({
            day_number: index + 1,
            date: `2026-12-0${index + 1}`,
            total_cost: 750,
            stops: [{ attraction_id: `a-${index + 1}`, cost: 750 }],
          })),
        },
});

test("legacy destination totals stay separate from complete-trip totals", () => {
  const result = buildBudgetDashboard(
    [trip(1)],
    [
      detail(1, [
        { id: "a-1", cost: 750, cost_known: true },
        { id: "a-2", cost: 750, cost_known: true },
      ]),
    ],
  );
  assert.equal(result.tripCount, 1);
  assert.equal(result.allocatedBudget, 10_000);
  assert.equal(result.estimatedCost, 0);
  assert.equal(result.legacyDestinationCost, 8_500);
  assert.equal(result.remainingBudget, null);
  assert.equal(result.dailyAverage, null);
  assert.deepEqual(
    result.dailyTrips[0]?.days.map((day) => day.cost),
    [750, 750],
  );
});

test("multiple trips keep legacy estimates separate and combined complete remaining unavailable", () => {
  const result = buildBudgetDashboard([trip(1), trip(2, { cost: null })]);
  assert.equal(result.allocatedBudget, 20_000);
  assert.equal(result.estimatedCost, 0);
  assert.equal(result.legacyDestinationCost, 8_500);
  assert.equal(result.legacyEstimateTripCount, 1);
  assert.equal(result.estimatedTripCount, 0);
  assert.equal(result.remainingBudget, null);
  assert.equal(result.allEstimatesAvailable, false);
});

test("no trips return empty, zero aggregate values without creating chart data", () => {
  const result = buildBudgetDashboard([]);
  assert.equal(result.tripCount, 0);
  assert.equal(result.estimatedCost, 0);
  assert.equal(result.remainingBudget, 0);
  assert.equal(result.dailyAverage, null);
  assert.deepEqual(result.dailyTrips, []);
});

test("budget status thresholds classify near-limit and over-budget estimates", () => {
  assert.equal(budgetStatus(7_999, 10_000)?.label, "Within Budget");
  assert.equal(budgetStatus(8_000, 10_000)?.label, "Near Budget Limit");
  assert.equal(budgetStatus(10_000, 10_000)?.label, "Near Budget Limit");
  assert.equal(budgetStatus(10_001, 10_000)?.label, "Over Budget");
});

test("missing category amounts are not converted to zero or represented as complete coverage", () => {
  const result = buildBudgetDashboard([
    trip(1, {
      categories: [
        { key: "accommodation", amount: 2000 },
        { key: "transportation", amount: null },
      ],
    }),
  ]);
  const transport = result.categories.find((category) => category.key === "local_transport");
  const food = result.categories.find((category) => category.key === "food");
  assert.equal(transport?.amount, null);
  assert.equal(transport?.coverage, 0);
  assert.equal(food?.coverage, 0);
});

test("ticket category is marked partial when unknown attraction fees were excluded", () => {
  const result = buildBudgetDashboard([trip(1, { unknownFees: 1 })]);
  const tickets = result.categories.find((category) => category.key === "attraction_fees");
  assert.equal(tickets?.partial, true);
});

const detail = (id, attractions) => ({ id, planning_inputs: { attractions } });

test("all known attraction fees produce a daily total for every itinerary day", () => {
  const savedTrip = trip(1);
  savedTrip.latest_itinerary.days[0].stops = [
    { attraction_id: "a-1", cost: 500 },
    { attraction_id: "a-extra", cost: 200 },
  ];
  savedTrip.latest_itinerary.days[1].stops = [{ attraction_id: "a-2", cost: 250 }];
  const result = buildBudgetDashboard(
    [savedTrip],
    [
      detail(1, [
        { id: "a-1", cost: 500, cost_known: true },
        { id: "a-extra", cost: 200, cost_known: true },
        { id: "a-2", cost: 250, cost_known: true },
      ]),
    ],
  );
  assert.deepEqual(
    result.dailyTrips[0]?.days.map(({ cost, status }) => [cost, status]),
    [
      [700, "available"],
      [250, "available"],
    ],
  );
});

test("mixed known and unknown fees keep known totals and clearly mark partial or unavailable days", () => {
  const savedTrip = trip(1);
  savedTrip.latest_itinerary.days[0].stops[0].cost = 500;
  savedTrip.latest_itinerary.days[1].stops[0].cost = 250;
  savedTrip.latest_itinerary.days[0].stops.push({ attraction_id: "unknown-day-one", cost: 0 });
  savedTrip.latest_itinerary.days[1].stops = [{ attraction_id: "unknown-day-two", cost: 0 }];
  const result = buildBudgetDashboard(
    [savedTrip],
    [
      detail(1, [
        { id: "a-1", cost: 500, cost_known: true },
        { id: "a-2", cost: 250, cost_known: true },
        { id: "unknown-day-one", cost: 0, cost_known: false },
        { id: "unknown-day-two", cost: 0, cost_known: false },
      ]),
    ],
  );
  assert.deepEqual(
    result.dailyTrips[0]?.days.map(({ cost, status }) => [cost, status]),
    [
      [500, "partial"],
      [null, "unavailable"],
    ],
  );
});

test("multiple trips retain separate day groups with different itinerary lengths", () => {
  const first = trip(1, { days: 1 });
  const second = trip(2, { days: 3 });
  first.latest_itinerary.days[0].stops[0].cost = 500;
  second.latest_itinerary.days.forEach((day, index) => {
    day.stops[0].cost = [200, 300, 400][index];
  });
  const result = buildBudgetDashboard(
    [first, second],
    [
      detail(1, [{ id: "a-1", cost: 500, cost_known: true }]),
      detail(2, [
        { id: "a-1", cost: 200, cost_known: true },
        { id: "a-2", cost: 300, cost_known: true },
        { id: "a-3", cost: 400, cost_known: true },
      ]),
    ],
  );
  assert.deepEqual(
    result.dailyTrips.map((group) => group.days.length),
    [1, 3],
  );
  assert.deepEqual(
    result.dailyTrips.map((group) => group.days[0]?.cost),
    [500, 200],
  );
});

test("unknown fees never become a zero-cost display value", () => {
  const result = buildBudgetDashboard(
    [trip(1)],
    [
      detail(1, [
        { id: "a-1", cost: 0, cost_known: false },
        { id: "a-2", cost: 0, cost_known: false },
      ]),
    ],
  );
  assert.equal(result.dailyTrips[0]?.days[0]?.cost, null);
  assert.equal(result.dailyTrips[0]?.days[0]?.status, "unavailable");
});

test("missing attraction availability metadata stays unavailable instead of trusting placeholder stop cost", () => {
  const result = buildBudgetDashboard([trip(1)]);
  assert.equal(result.dailyTrips[0]?.days[0]?.cost, null);
  assert.equal(result.dailyTrips[0]?.days[0]?.status, "unavailable");
});

test("actual expense data is not synthesized", () => {
  const result = buildBudgetDashboard([trip(1)]);
  assert.equal("actualCosts" in result, false);
  assert.equal("actual" in (result.dailyTrips[0]?.days[0] ?? {}), false);
});

test("daily budget UI labels partial and unavailable days and lets travelers choose a trip", () => {
  assert.match(budgetPage, /Choose trip for daily budget overview/);
  assert.match(budgetPage, /dayLabel: `Day \$\{day\.dayNumber\}`/);
  assert.match(budgetPage, /Cost unavailable/);
  assert.match(budgetPage, /Partial/);
  assert.match(budgetPage, /Unknown fees\s+are excluded/);
});

const completeTrip = (id, total, categories, options = {}) => ({
  ...trip(id, { budget: options.budget ?? 10_000 }),
  itinerary_stale: options.stale ?? false,
  complete_budget_current: options.current ?? true,
  latest_itinerary: {
    ...trip(id).latest_itinerary,
    budget_estimate: {
      complete_budget: {
        total_estimate: total,
        categories,
      },
    },
    days: trip(id).latest_itinerary.days,
  },
});

test("current complete budgets aggregate across trips without mixing legacy destination estimates", () => {
  const result = buildBudgetDashboard([
    completeTrip(1, 5000, [
      { key: "intercity_outbound", amount: 1000, status: "user_provided" },
      { key: "food", amount: 1500, status: "estimated" },
    ]),
    trip(2, { cost: 7000 }),
    completeTrip(3, 3000, [
      { key: "intercity_outbound", amount: 500, status: "user_provided" },
      { key: "food", amount: null, status: "unavailable" },
    ]),
  ]);
  assert.equal(result.estimatedCost, 8000);
  assert.equal(result.estimatedTripCount, 2);
  assert.equal(result.legacyDestinationCost, 7000);
  assert.equal(result.legacyEstimateTripCount, 1);
  assert.equal(result.remainingBudget, null);
  assert.equal(result.categoryDataScope, "complete_trip");
  assert.equal(result.categories.find(({ key }) => key === "intercity_outbound")?.amount, 1500);
  assert.equal(result.categories.find(({ key }) => key === "food")?.amount, 1500);
  assert.equal(result.categories.find(({ key }) => key === "food")?.partial, true);
});

test("incomplete and stale complete budgets are not counted as complete totals or current daily groups", () => {
  const result = buildBudgetDashboard([
    completeTrip(1, null, [{ key: "intercity_return", amount: null, status: "unavailable" }]),
    completeTrip(2, 4000, [{ key: "food", amount: 4000, status: "estimated" }], { stale: true }),
  ]);
  assert.equal(result.estimatedCost, 0);
  assert.equal(result.incompleteBudgetTripCount, 1);
  assert.equal(result.staleTripCount, 1);
  assert.equal(result.remainingBudget, null);
  assert.deepEqual(
    result.dailyTrips.map(({ tripId }) => tripId),
    [1],
  );
});
