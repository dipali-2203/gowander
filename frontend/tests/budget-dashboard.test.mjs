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
  const result = buildBudgetDashboard([trip(1)]);
  assert.equal(result.tripCount, 1);
  assert.equal(result.allocatedBudget, 10_000);
  assert.equal(result.estimatedCost, 0);
  assert.equal(result.legacyDestinationCost, 8_500);
  assert.equal(result.remainingBudget, null);
  assert.equal(result.dailyAverage, null);
  assert.deepEqual(
    result.dailyTrips[0]?.days.map((day) => day.cost),
    [null, null],
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

test("successfully estimated original unknown fees are not counted as unresolved", () => {
  const result = buildBudgetDashboard([
    {
      ...completeTrip(1, 5000, [
        {
          key: "attraction_fees",
          amount: 600,
          status: "estimated",
          estimated_count: 2,
          unresolved_count: 0,
        },
      ]),
      latest_itinerary: {
        ...completeTrip(1, 5000, []).latest_itinerary,
        budget_estimate: {
          unknown_attraction_fee_count: 2,
          unresolved_attraction_fee_count: 0,
          complete_budget: {
            total_estimate: 5000,
            categories: [
              {
                key: "attraction_fees",
                amount: 600,
                status: "estimated",
                estimated_count: 2,
                unresolved_count: 0,
              },
            ],
          },
        },
      },
    },
  ]);
  const tickets = result.categories.find((category) => category.key === "attraction_fees");
  assert.equal(tickets?.partial, false);
  assert.deepEqual(result.attractionFeeStats, {
    originalUnknownCount: 2,
    estimatedCount: 2,
    unresolvedCount: 0,
  });
});

test("partly unresolved fees keep estimate and unresolved counts separate", () => {
  const result = buildBudgetDashboard([
    {
      ...completeTrip(1, null, []),
      latest_itinerary: {
        ...completeTrip(1, null, []).latest_itinerary,
        budget_estimate: {
          unknown_attraction_fee_count: 3,
          unresolved_attraction_fee_count: 1,
          complete_budget: {
            total_estimate: null,
            categories: [
              {
                key: "attraction_fees",
                amount: 400,
                status: "partial",
                estimated_count: 2,
                unresolved_count: 1,
              },
            ],
          },
        },
      },
    },
  ]);
  const tickets = result.categories.find((category) => category.key === "attraction_fees");
  assert.equal(tickets?.partial, true);
  assert.deepEqual(result.attractionFeeStats, {
    originalUnknownCount: 3,
    estimatedCount: 2,
    unresolvedCount: 1,
  });
});

test("dashboard derives unresolved fees after subtracting successful estimates when needed", () => {
  const saved = trip(1, { unknownFees: 5 });
  saved.latest_itinerary.budget_estimate.categories = [
    { key: "attractions", amount: 300, estimated_count: 3 },
  ];
  const result = buildBudgetDashboard([saved]);
  assert.deepEqual(result.attractionFeeStats, {
    originalUnknownCount: 5,
    estimatedCount: 3,
    unresolvedCount: 2,
  });
});

const feeDay = (day_number, values = {}) => ({
  day_number,
  date: `2026-12-0${day_number}`,
  scheduled_unique_attraction_count: 1,
  fee_counted_attraction_count: 1,
  verified_fee_total: 0,
  estimated_fee_lower_total: 0,
  estimated_fee_representative_total: 0,
  estimated_fee_upper_total: 0,
  representative_total: 0,
  lower_total: 0,
  upper_total: 0,
  unresolved_attraction_count: 0,
  status: "no_attractions",
  attractions: [],
  ...values,
});

const withDailyFees = (savedTrip, dailyFees) => {
  savedTrip.latest_itinerary.budget_estimate.daily_attraction_fees = dailyFees;
  return savedTrip;
};

test("daily chart uses backend estimates even when optimizer stop costs are zero", () => {
  const savedTrip = trip(1);
  savedTrip.latest_itinerary.days[0].stops[0].cost = 0;
  const result = buildBudgetDashboard([
    withDailyFees(savedTrip, [
      feeDay(1, {
        status: "estimated",
        scheduled_unique_attraction_count: 2,
        estimated_fee_lower_total: 100,
        estimated_fee_representative_total: 300,
        estimated_fee_upper_total: 1000,
        representative_total: 300,
        lower_total: 100,
        upper_total: 1000,
        attractions: [{ status: "estimated" }, { status: "estimated" }],
      }),
      feeDay(2, {
        status: "partial",
        verified_fee_total: 50,
        estimated_fee_lower_total: 0,
        estimated_fee_representative_total: 100,
        estimated_fee_upper_total: 400,
        representative_total: 150,
        lower_total: 50,
        upper_total: 450,
        unresolved_attraction_count: 1,
        attractions: [{ status: "verified" }, { status: "estimated" }],
      }),
    ]),
  ]);
  const daily = result.dailyTrips[0];
  assert.equal(daily.hasFeeData, true);
  assert.deepEqual(
    daily.days.map(({ cost, status, verifiedAmount, estimatedAmount }) => [
      cost,
      status,
      verifiedAmount,
      estimatedAmount,
    ]),
    [
      [300, "estimated", 0, 300],
      [150, "partial", 50, 100],
    ],
  );
});

test("unknown daily fees remain unavailable instead of becoming zero", () => {
  const result = buildBudgetDashboard([
    withDailyFees(trip(1), [
      feeDay(1, {
        status: "unavailable",
        fee_counted_attraction_count: 1,
        unresolved_attraction_count: 1,
        attractions: [{ status: "unavailable" }],
      }),
      feeDay(2, {
        status: "no_attractions",
        scheduled_unique_attraction_count: 0,
        fee_counted_attraction_count: 0,
      }),
    ]),
  ]);
  assert.equal(result.dailyTrips[0]?.hasFeeData, false);
  assert.equal(result.dailyTrips[0]?.days[0]?.cost, null);
  assert.equal(result.dailyTrips[0]?.days[0]?.status, "unavailable");
  assert.equal(result.dailyTrips[0]?.days[0]?.unknownCount, 1);
  assert.equal(result.dailyTrips[0]?.days[1]?.cost, 0);
  assert.equal(result.dailyTrips[0]?.days[1]?.status, "no_attractions");
});

test("multiple trips retain separate daily estimate groups and itinerary lengths", () => {
  const first = withDailyFees(trip(1, { days: 1 }), [
    feeDay(1, {
      status: "verified",
      verified_fee_total: 500,
      representative_total: 500,
      lower_total: 500,
      upper_total: 500,
      attractions: [{ status: "verified" }],
    }),
  ]);
  const second = withDailyFees(trip(2, { days: 3 }), [
    feeDay(1, {
      status: "estimated",
      estimated_fee_representative_total: 200,
      representative_total: 200,
      attractions: [{ status: "estimated" }],
    }),
    feeDay(2, {
      status: "estimated",
      estimated_fee_representative_total: 300,
      representative_total: 300,
      attractions: [{ status: "estimated" }],
    }),
    feeDay(3, {
      status: "estimated",
      estimated_fee_representative_total: 400,
      representative_total: 400,
      attractions: [{ status: "estimated" }],
    }),
  ]);
  const result = buildBudgetDashboard([first, second]);
  assert.deepEqual(
    result.dailyTrips.map((group) => group.days.length),
    [1, 3],
  );
  assert.deepEqual(
    result.dailyTrips.map((group) => group.days[0]?.cost),
    [500, 200],
  );
  assert.equal(result.dailyTrips[0].days[0].knownCount, 1);
  assert.equal(result.dailyTrips[1].days[0].estimatedCount, 1);
});

test("repeated attractions already charged on an earlier day are not counted again", () => {
  const result = buildBudgetDashboard([
    withDailyFees(trip(1), [
      feeDay(1, {
        status: "estimated",
        estimated_fee_representative_total: 300,
        representative_total: 300,
        attractions: [{ status: "estimated" }],
      }),
      feeDay(2, {
        status: "already_counted",
        fee_counted_attraction_count: 0,
        representative_total: 0,
        attractions: [],
      }),
    ]),
  ]);
  assert.equal(result.dailyTrips[0].days[0].cost, 300);
  assert.equal(result.dailyTrips[0].days[1].cost, null);
  assert.equal(result.dailyTrips[0].days[1].status, "already_counted");
});

test("old snapshots without backend daily fee data never fall back to optimizer costs", () => {
  const result = buildBudgetDashboard([trip(1)]);
  assert.equal(result.dailyTrips[0]?.breakdownAvailable, false);
  assert.equal(result.dailyTrips[0]?.hasFeeData, false);
  assert.equal(result.dailyTrips[0]?.days[0]?.cost, null);
  assert.equal(result.dailyTrips[0]?.days[0]?.status, "unavailable");
});

test("daily budget UI identifies backend fee estimates and unavailable days", () => {
  assert.match(budgetPage, /Choose trip for daily budget overview/);
  assert.match(budgetPage, /dayLabel: `Day \$\{day\.dayNumber\}`/);
  assert.match(budgetPage, /Fee estimate unavailable/);
  assert.match(budgetPage, /Verified fee/);
  assert.match(budgetPage, /Estimated fee/);
  assert.match(budgetPage, /same verified and versioned estimates/);
  assert.doesNotMatch(budgetPage, /optimizer itinerary costs and exclude unknown fees/);
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
