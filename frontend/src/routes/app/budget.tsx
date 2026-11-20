import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  ChartNoAxesCombined,
  CircleDollarSign,
  PiggyBank,
  Wallet,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EmptyState, PageHeader } from "@/components/travel/PageHeader";
import { TripBudgetEstimatePanel } from "@/components/travel/TripBudgetEstimatePanel";
import { Button } from "@/components/ui/button";
import { getUserTrips, type AccountTrip } from "@/lib/api";
import { budgetStatus, buildBudgetDashboard } from "@/lib/budget-dashboard.mjs";

export const Route = createFileRoute("/app/budget")({
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Budget Dashboard · GoWander" },
      {
        name: "description",
        content: "Review estimated costs and allocated budgets for your trips.",
      },
    ],
  }),
  component: Budget,
});

const inr = (amount: number) => `₹${Math.round(amount).toLocaleString("en-IN")}`;
const statusTone = {
  success: "text-emerald-700 bg-emerald-500/10 dark:text-emerald-300",
  warning: "text-amber-700 bg-amber-500/10 dark:text-amber-300",
  danger: "text-destructive bg-destructive/10",
} as const;

function Budget() {
  const [trips, setTrips] = useState<AccountTrip[]>([]);
  const [selectedDailyTripId, setSelectedDailyTripId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    getUserTrips()
      .then((items) => {
        if (active) setTrips(items);
      })
      .catch((cause) => {
        if (active)
          setError(cause instanceof Error ? cause.message : "Could not load your trip budgets.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const dashboard = useMemo(() => buildBudgetDashboard(trips), [trips]);
  const categoryTotal = dashboard.categories.reduce(
    (sum, category) => sum + (category.amount ?? 0),
    0,
  );
  const chartCategories = dashboard.categories.filter(
    (category) => category.amount !== null && category.amount > 0,
  );
  const overallStatus =
    dashboard.remainingBudget === null
      ? null
      : budgetStatus(dashboard.estimatedCost, dashboard.allocatedBudget);
  const activeDailyTrip =
    dashboard.dailyTrips.find((trip) => trip.tripId === selectedDailyTripId) ??
    dashboard.dailyTrips[0];

  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        title="Budget dashboard"
        description="See how your planned budgets compare with the latest trip estimates. Estimates are not recorded expenses."
      />
      {error && (
        <p className="surface p-4 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      {loading ? (
        <div className="surface p-6 text-sm text-muted-foreground" role="status">
          Loading your budgets…
        </div>
      ) : trips.length === 0 ? (
        <EmptyState
          title="No trip budgets yet."
          description="Create a trip to see its planned budget and cost estimates here."
          action={
            <Button asChild>
              <Link to="/app/planner">Plan a trip</Link>
            </Button>
          }
        />
      ) : (
        <>
          <section aria-label="Budget summary" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <SummaryCard
              label="Total Planned Budget"
              value={inr(dashboard.allocatedBudget)}
              hint={`Across ${trips.length} saved ${trips.length === 1 ? "trip" : "trips"}`}
              icon={<Wallet />}
            />
            <SummaryCard
              label="Complete Trip Cost"
              value={dashboard.estimatedTripCount ? inr(dashboard.estimatedCost) : "Unavailable"}
              hint={`Calculable complete totals for ${dashboard.estimatedTripCount} of ${trips.length} trips`}
              icon={<CircleDollarSign />}
            />
            <SummaryCard
              label="Legacy Destination Estimates"
              value={
                dashboard.legacyEstimateTripCount
                  ? inr(dashboard.legacyDestinationCost)
                  : "Unavailable"
              }
              hint={
                dashboard.legacyEstimateTripCount
                  ? `${dashboard.legacyEstimateTripCount} trip(s); intercity costs excluded and kept separate`
                  : "No legacy destination-only estimates"
              }
              icon={<CircleDollarSign />}
            />
            <SummaryCard
              label="Remaining Budget"
              value={
                dashboard.remainingBudget === null ? "Unavailable" : inr(dashboard.remainingBudget)
              }
              hint={
                dashboard.remainingBudget === null
                  ? "Requires a current calculable complete budget for every saved trip"
                  : dashboard.remainingBudget < 0
                    ? "Estimated costs exceed allocation"
                    : "Planned budget less estimates"
              }
              icon={
                dashboard.remainingBudget !== null && dashboard.remainingBudget < 0 ? (
                  <ArrowUpRight />
                ) : (
                  <ArrowDownRight />
                )
              }
              accent
            />
            <SummaryCard
              label="Daily Average"
              value={dashboard.dailyAverage === null ? "Unavailable" : inr(dashboard.dailyAverage)}
              hint={
                dashboard.dailyAverage === null
                  ? "No current complete trip duration estimate available"
                  : `Based on ${dashboard.estimatedTripCount} calculable complete budget(s)`
              }
              icon={<CalendarDays />}
            />
          </section>

          <div className="grid gap-5 xl:grid-cols-[1.1fr_1fr]">
            <section className="surface min-w-0 p-5 sm:p-6">
              <SectionHeading
                title="Expense breakdown"
                subtitle={
                  dashboard.categoryDataScope === "complete_trip"
                    ? "Current complete-trip categories; legacy destination estimates are not mixed in"
                    : dashboard.categoryDataScope === "destination_only"
                      ? "Legacy destination-only categories; intercity travel is excluded"
                      : "No current budget categories are available"
                }
                icon={<ChartNoAxesCombined />}
              />
              {categoryTotal > 0 ? (
                <div className="mt-4 grid items-center gap-3 md:grid-cols-[minmax(180px,0.9fr)_1.1fr]">
                  <div
                    className="h-56 min-w-0"
                    role="img"
                    aria-label="Donut chart showing estimated trip costs by category"
                  >
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={chartCategories}
                          dataKey="amount"
                          nameKey="label"
                          innerRadius="58%"
                          outerRadius="82%"
                          paddingAngle={3}
                        >
                          {chartCategories.map((category) => (
                            <Cell key={category.key} fill={category.color} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value) => inr(Number(value))} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <ul className="space-y-3">
                    {dashboard.categories.map((category) => (
                      <li
                        key={category.key}
                        className="flex items-center justify-between gap-3 text-sm"
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <span
                            className="h-2.5 w-2.5 shrink-0 rounded-full"
                            style={{ backgroundColor: category.color }}
                          />
                          <span className="truncate">{category.label}</span>
                        </span>
                        <span className="shrink-0 text-right font-medium">
                          {category.coverage && category.amount !== null
                            ? inr(category.amount)
                            : "Unavailable"}
                          {category.coverage > 0 && (
                            <span className="ml-1 text-xs font-normal text-muted-foreground">
                              {category.percentage.toFixed(0)}%
                              {category.partial ? " · partial" : ""}
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="mt-5 rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                  Category estimates are not available yet.
                </div>
              )}
              {dashboard.categoryEstimateTripCount < trips.length && (
                <p className="mt-4 text-xs text-muted-foreground">
                  Breakdown uses {dashboard.categoryEstimateTripCount} trip(s) with compatible
                  category estimates. Incomplete, stale, and other-scope estimates are not mixed
                  into these category totals.
                </p>
              )}
              {(dashboard.attractionFeeStats.originalUnknownCount > 0 ||
                dashboard.attractionFeeStats.estimatedCount > 0 ||
                dashboard.attractionFeeStats.unresolvedCount > 0) && (
                <p className="mt-3 rounded-lg bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-200">
                  Attraction fees: {dashboard.attractionFeeStats.originalUnknownCount} original
                  catalog fee(s) unknown, {dashboard.attractionFeeStats.estimatedCount} estimated,
                  and {dashboard.attractionFeeStats.unresolvedCount} still unresolved. Estimates are
                  separate from verified catalog prices.
                </p>
              )}
              {dashboard.incompleteBudgetTripCount > 0 && (
                <p className="mt-3 rounded-lg bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-200">
                  {dashboard.incompleteBudgetTripCount} current complete-budget estimate(s) have
                  unavailable or partial categories. Those costs are not counted as zero in complete
                  trip totals.
                </p>
              )}
              {dashboard.staleTripCount > 0 && (
                <p className="mt-3 rounded-lg bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-200">
                  {dashboard.staleTripCount} saved trip(s) have outdated itinerary estimates and are
                  excluded until regenerated.
                </p>
              )}
            </section>

            <section className="surface min-w-0 p-5 sm:p-6">
              <SectionHeading
                title="Daily budget overview"
                subtitle="Daily attraction fee estimates"
                icon={<CalendarDays />}
              />
              {dashboard.dailyTrips.length > 1 && (
                <label className="mt-4 flex items-center gap-3 text-sm">
                  <span className="font-medium">Trip</span>
                  <select
                    className="h-9 min-w-0 flex-1 rounded-lg border border-input bg-background px-3 text-sm"
                    value={activeDailyTrip?.tripId ?? ""}
                    onChange={(event) => setSelectedDailyTripId(Number(event.target.value))}
                    aria-label="Choose trip for daily budget overview"
                  >
                    {dashboard.dailyTrips.map((trip) => (
                      <option key={trip.tripId} value={trip.tripId}>
                        {trip.tripName} · {trip.destination}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {dashboard.dailyTrips.length > 0 && activeDailyTrip?.hasFeeData ? (
                <div
                  className="mt-5 h-64 min-w-0"
                  aria-label={`Daily attraction fee estimates for ${activeDailyTrip.tripName}`}
                >
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={
                        activeDailyTrip?.days.map((day) => ({
                          ...day,
                          dayLabel: `Day ${day.dayNumber}`,
                        })) ?? []
                      }
                      margin={{ top: 8, right: 8, left: 2, bottom: 35 }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 3"
                        vertical={false}
                        stroke="var(--border)"
                      />
                      <XAxis
                        dataKey="dayLabel"
                        interval={0}
                        tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                      />
                      <YAxis
                        hide={!activeDailyTrip?.days.some((day) => day.cost !== null)}
                        tickFormatter={(value) => `₹${Number(value).toLocaleString("en-IN")}`}
                        tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                        width={72}
                      />
                      <Tooltip
                        content={({ active, payload, label }) => {
                          if (!active || !payload?.length) return null;
                          const point = payload[0]?.payload;
                          return (
                            <div className="rounded-lg border border-border bg-background p-3 text-xs shadow-md">
                              <p className="font-semibold">
                                {label} · {point?.date}
                              </p>
                              <p>Verified fees: {inr(point?.verifiedAmount ?? 0)}</p>
                              <p>
                                Estimated fees: {inr(point?.estimatedAmount ?? 0)}
                                {typeof point?.estimatedLower === "number" &&
                                typeof point?.estimatedUpper === "number"
                                  ? ` · range ${inr(point.estimatedLower)}–${inr(point.estimatedUpper)}`
                                  : ""}
                              </p>
                              {point?.unknownCount > 0 && (
                                <p>{point.unknownCount} attraction fee(s) unavailable</p>
                              )}
                              <p>
                                {point?.scheduledUniqueCount ?? 0} unique scheduled attraction(s)
                              </p>
                            </div>
                          );
                        }}
                      />
                      <Bar
                        dataKey="verifiedAmount"
                        name="Verified fees"
                        stackId="fees"
                        fill="#0f766e"
                      />
                      <Bar
                        dataKey="estimatedAmount"
                        name="Estimated fees"
                        stackId="fees"
                        fill="#a855f7"
                        radius={[5, 5, 0, 0]}
                      >
                        {activeDailyTrip.days.map((day) => (
                          <Cell
                            key={day.dayNumber}
                            fill={day.status === "partial" ? "#f59e0b" : "#a855f7"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : dashboard.dailyTrips.length > 0 ? (
                <div className="mt-5 rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                  {activeDailyTrip?.breakdownAvailable
                    ? "No verified or estimated attraction fees are available for this trip's scheduled days. Unknown fees are not treated as free."
                    : "Daily attraction fee estimates are unavailable for this saved itinerary. Regenerate the itinerary to create a current backend fee breakdown."}
                </div>
              ) : (
                <div className="mt-5 rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                  Daily attraction fees are unavailable because no saved itinerary with day-level
                  activities is available yet.
                </div>
              )}
              {activeDailyTrip?.hasFeeData && (
                <div
                  className="mt-2 flex flex-wrap gap-4 text-xs text-muted-foreground"
                  aria-label="Daily fee chart legend"
                >
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm bg-teal-700" />
                    Verified fee
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm bg-purple-500" />
                    Estimated fee
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm bg-amber-500" />
                    Partial day
                  </span>
                </div>
              )}
              {activeDailyTrip && (
                <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                  {activeDailyTrip.days.map((day) => (
                    <li
                      key={day.dayNumber}
                      className="flex items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2 text-sm"
                    >
                      <span>
                        <span className="font-medium">Day {day.dayNumber}</span>
                        <span className="ml-2 text-xs text-muted-foreground">{day.date}</span>
                      </span>
                      <span className="shrink-0 font-medium">
                        {day.status === "no_attractions"
                          ? "No attractions scheduled"
                          : day.status === "already_counted"
                            ? "Fees counted on an earlier day"
                            : day.status === "unavailable"
                              ? "Fee estimate unavailable"
                              : `${day.knownCount ? `Verified ${inr(day.verifiedAmount ?? 0)}` : ""}${day.knownCount && day.estimatedCount ? " · " : ""}${day.estimatedCount ? `Estimated ${inr(day.estimatedAmount ?? 0)}` : ""}`}
                        {day.status === "partial" && (
                          <span className="ml-1 text-xs font-normal text-amber-700 dark:text-amber-300">
                            · Partial
                          </span>
                        )}
                        {day.unknownCount > 0 && (
                          <span className="ml-1 text-xs font-normal text-muted-foreground">
                            · {day.unknownCount} unavailable
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {dashboard.dailyTrips.length > 0 && (
                <p className="mt-3 text-xs text-muted-foreground">
                  Daily attraction fee estimates use the same verified and versioned estimates as
                  the complete-trip budget. Estimated fees are not verified ticket prices. The chart
                  excludes accommodation, food, transportation and miscellaneous costs; the
                  optimizer's activity costs remain separate.
                </p>
              )}
            </section>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <section className="surface p-5 sm:p-6">
              <SectionHeading
                title="Budget health"
                subtitle="Based on the available trip estimates"
                icon={<PiggyBank />}
              />
              {overallStatus && dashboard.remainingBudget !== null ? (
                <>
                  <div className="mt-5 flex flex-wrap items-end justify-between gap-3">
                    <div>
                      <p className="text-2xl font-semibold">
                        {inr(dashboard.estimatedCost)}{" "}
                        <span className="text-sm font-normal text-muted-foreground">estimated</span>
                      </p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        of {inr(dashboard.allocatedBudget)} allocated
                      </p>
                    </div>
                    <span
                      className={`rounded-full px-3 py-1 text-xs font-semibold ${statusTone[overallStatus.tone]}`}
                    >
                      {overallStatus.label}
                    </span>
                  </div>
                  <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className={`h-full rounded-full ${overallStatus.tone === "danger" ? "bg-destructive" : overallStatus.tone === "warning" ? "bg-amber-500" : "bg-primary"}`}
                      style={{ width: `${Math.min(overallStatus.used, 100)}%` }}
                    />
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-muted-foreground">
                    <span>{overallStatus.used.toFixed(0)}% used</span>
                    <span>Remaining {inr(dashboard.remainingBudget)}</span>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    Status thresholds: under 80% on track · 80–100% near limit · over 100% over
                    budget.
                  </p>
                </>
              ) : (
                <p className="mt-5 rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">
                  Current calculable complete-trip estimates for every saved trip are needed to
                  calculate combined budget health. Legacy destination estimates are shown
                  separately and are not used as journey-wide totals.
                </p>
              )}
              <div className="mt-5 space-y-3 border-t border-border pt-4">
                {dashboard.categories.map((category) => (
                  <div key={category.key}>
                    <div className="mb-1 flex justify-between gap-3 text-xs">
                      <span>{category.label}</span>
                      <span className="text-muted-foreground">
                        {category.coverage && category.amount !== null
                          ? `${category.percentage.toFixed(0)}% · ${inr(category.amount)}${category.partial ? " · partial" : ""}`
                          : "Unavailable"}
                      </span>
                    </div>
                    {category.coverage > 0 && (
                      <div className="h-1.5 rounded-full bg-muted">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.min(category.percentage, 100)}%`,
                            backgroundColor: category.color,
                          }}
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
            <section className="surface p-5 sm:p-6">
              <SectionHeading
                title="Savings suggestions"
                subtitle="Only evidence-based opportunities are shown"
                icon={<PiggyBank />}
              />
              <div className="mt-5 flex min-h-36 flex-col items-center justify-center rounded-xl border border-dashed border-border px-5 text-center">
                <PiggyBank className="mb-3 h-7 w-7 text-muted-foreground" aria-hidden="true" />
                <p className="text-sm font-medium">
                  No savings opportunities identified for your current itinerary.
                </p>
                <p className="mt-1 max-w-sm text-xs text-muted-foreground">
                  We do not have comparable live prices or spending records to support a savings
                  recommendation yet.
                </p>
              </div>
            </section>
          </div>

          <section className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="text-xl font-semibold tracking-tight">Trip budgets</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Current estimates and remaining planned budget for each saved trip.
                </p>
              </div>
              <span className="text-xs text-muted-foreground">
                {trips.length} {trips.length === 1 ? "trip" : "trips"}
              </span>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              {trips.map((trip) => (
                <TripBudgetCard key={trip.id} trip={trip} />
              ))}
            </div>
          </section>
          <p className="text-xs text-muted-foreground">
            All cost figures are estimates from saved itinerary data and configured allowances.
            Actual expenses, bookings and payments are not tracked.
          </p>
        </>
      )}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  hint,
  icon,
  accent = false,
}: {
  label: string;
  value: string;
  hint: string;
  icon: React.ReactNode;
  accent?: boolean;
}) {
  return (
    <article
      className={`surface relative overflow-hidden p-5 ${accent ? "border-primary/30" : ""}`}
    >
      {accent && <span className="absolute inset-y-0 left-0 w-1 bg-primary" />}
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary-soft text-primary">
          {icon}
        </span>
      </div>
      <p className="mt-4 break-words text-2xl font-semibold tracking-tight sm:text-3xl">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </article>
  );
}

function SectionHeading({
  title,
  subtitle,
  icon,
}: {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary">
        {icon}
      </span>
      <div>
        <h2 className="font-semibold">{title}</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
      </div>
    </div>
  );
}

function TripBudgetCard({ trip }: { trip: AccountTrip }) {
  const estimate = trip.latest_itinerary?.budget_estimate;
  const completeBudget = estimate?.complete_budget;
  const attractionFeeCategory =
    completeBudget?.categories?.find((category) => category.key === "attraction_fees") ??
    estimate?.categories?.find((category) => category.key === "attractions");
  const originalUnknownFees = estimate?.unknown_attraction_fee_count ?? 0;
  const estimatedFees = attractionFeeCategory?.estimated_count ?? 0;
  const unresolvedFees =
    estimate?.unresolved_attraction_fee_count ??
    attractionFeeCategory?.unresolved_count ??
    Math.max(0, originalUnknownFees - estimatedFees);
  const completeIsCurrent = Boolean(completeBudget && trip.complete_budget_current);
  const total = completeIsCurrent ? completeBudget?.total_estimate : null;
  const remaining =
    completeIsCurrent && typeof completeBudget?.remaining_budget === "number"
      ? completeBudget.remaining_budget
      : null;
  const status =
    completeIsCurrent &&
    typeof total === "number" &&
    typeof completeBudget?.within_budget === "boolean"
      ? completeBudget?.within_budget === false
        ? { label: "Over Budget", tone: "danger" as const }
        : { label: "Within Estimated Range", tone: "success" as const }
      : null;
  const start = Date.parse(`${trip.start_date}T00:00:00Z`);
  const end = Date.parse(`${trip.end_date}T00:00:00Z`);
  const days =
    Number.isFinite(start) && Number.isFinite(end) && end >= start
      ? Math.floor((end - start) / 86_400_000) + 1
      : null;
  return (
    <article className="surface p-5 transition-colors hover:border-primary/40">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{trip.name || trip.destination}</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {trip.destination} · {trip.start_date} – {trip.end_date}
            {days !== null && (
              <>
                {" "}
                · {days} {days === 1 ? "day" : "days"}
              </>
            )}
          </p>
        </div>
        {status && (
          <span
            className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusTone[status.tone]}`}
          >
            {status.label}
          </span>
        )}
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Metric label="Allocated" value={inr(trip.budget)} />
        <Metric
          label="Current complete trip cost"
          value={
            typeof total === "number"
              ? inr(total)
              : completeBudget && completeIsCurrent
                ? "Incomplete"
                : completeBudget
                  ? "Refresh required"
                  : "Unavailable"
          }
        />
        <Metric
          label="Remaining at upper estimate"
          value={remaining === null ? "Unavailable" : inr(remaining)}
          emphasis={remaining !== null && remaining < 0}
        />
      </div>
      {originalUnknownFees > 0 && (
        <p className="mt-3 text-xs text-amber-700 dark:text-amber-300">
          Catalog amounts missing: {originalUnknownFees} · covered by estimates: {estimatedFees} ·
          still unresolved: {unresolvedFees}. Estimates are planning assumptions, not verified
          ticket prices.
        </p>
      )}
      {!completeBudget &&
        typeof estimate?.total_estimated === "number" &&
        trip.itinerary_stale !== true && (
          <p className="mt-3 text-xs text-muted-foreground">
            Legacy destination-only estimate: {inr(estimate.total_estimated)}. Intercity outbound
            and return costs are excluded.
          </p>
        )}
      {estimate && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-primary">
            Budget details
          </summary>
          <div className="mt-3">
            <TripBudgetEstimatePanel
              estimate={estimate}
              completeBudgetCurrent={trip.complete_budget_current}
              estimateIsCurrent={trip.itinerary_stale !== true}
            />
          </div>
        </details>
      )}
      {trip.selected_accommodation && (
        <p className="mt-2 text-xs text-muted-foreground">
          Selected stay: {trip.selected_accommodation.name}
          {trip.selected_accommodation.price_status === "unavailable"
            ? " · price unavailable"
            : " · sourced price"}
        </p>
      )}
      <div className="mt-4 border-t border-border pt-3">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/app/itinerary" search={{ tripId: trip.id }}>
            View itinerary
          </Link>
        </Button>
      </div>
    </article>
  );
}

function Metric({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-lg bg-muted/50 p-3">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className={`mt-1 truncate text-sm font-semibold ${emphasis ? "text-destructive" : ""}`}>
        {value}
      </p>
    </div>
  );
}
