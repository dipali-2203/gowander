import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { motion } from "motion/react";
import {
  Sun,
  CloudSun,
  Clock,
  Navigation,
  BedDouble,
  Wallet,
  Pencil,
  RefreshCw,
  Download,
  Share2,
} from "lucide-react";
import { toast } from "sonner";
import { EmptyState, PageHeader } from "@/components/travel/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { useTripStore } from "@/store/trip";
import {
  getTrip,
  getUserTrips,
  loadConditions,
  replanScenario,
  simulateReliability,
  submitPreferenceFeedback,
  type ConditionsResult,
  type ReliabilityResult,
  type ScenarioResult,
  type AccountTrip,
} from "@/lib/api";

export const Route = createFileRoute("/app/itinerary")({
  validateSearch: (search: Record<string, unknown>) => ({
    tripId: typeof search["tripId"] === "string" ? Number(search["tripId"]) : undefined,
  }),
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Your Itinerary · GoWander" },
      {
        name: "description",
        content:
          "A day-by-day baseline itinerary with scheduled activities, estimated travel time, attraction fees and risk assumptions.",
      },
      { property: "og:title", content: "Your Itinerary · GoWander" },
      {
        property: "og:description",
        content: "A day-by-day baseline itinerary with estimated travel and attraction fees.",
      },
    ],
  }),
  component: Itinerary,
});

function formatClock(minute: number) {
  const hours = Math.floor(minute / 60) % 24;
  const minutes = minute % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function Itinerary() {
  const { tripId: requestedTripId } = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  const generated = useTripStore((state) => state.generated);
  const generatedDestination = useTripStore((state) => state.generatedDestination);
  const alternatives = useTripStore((state) => state.alternatives);
  const planningAttractions = useTripStore((state) => state.planningAttractions);
  const planningStartLocation = useTripStore((state) => state.planningStartLocation);
  const planningBudget = useTripStore((state) => state.planningBudget);
  const setGenerated = useTripStore((state) => state.setGenerated);
  const clearTrip = useTripStore((state) => state.clear);
  const annealing = useTripStore((state) => state.annealing);
  const [scenario, setScenario] = useState<ScenarioResult | null>(null);
  const [replanning, setReplanning] = useState(false);
  const [reliability, setReliability] = useState<ReliabilityResult | null>(null);
  const [conditions, setConditions] = useState<ConditionsResult | null>(null);
  const [remainingBudget, setRemainingBudget] = useState(60000);
  const [remainingMinutes, setRemainingMinutes] = useState(1200);
  const [completedAttractionIds, setCompletedAttractionIds] = useState<string[]>([]);
  const [savedTrips, setSavedTrips] = useState<AccountTrip[]>([]);
  const [selectedTripId, setSelectedTripId] = useState<number | null>(generated?.trip_id ?? null);
  const [loadingTripList, setLoadingTripList] = useState(true);
  const [loadingSavedTrip, setLoadingSavedTrip] = useState(false);

  const restoreTrip = async (tripId: number) => {
    setLoadingSavedTrip(true);
    try {
      const saved = await getTrip(tripId);
      const itinerary = saved.latest_itinerary;
      if (!itinerary || !Array.isArray(itinerary.days)) {
        throw new Error("This saved trip does not have a multi-day itinerary yet.");
      }
      setGenerated(
        itinerary,
        saved.destination,
        saved.optimization_results.pareto ?? [],
        saved.planning_inputs?.attractions ?? [],
        [saved.start_latitude, saved.start_longitude],
        saved.budget,
        saved.optimization_results.simulated_annealing ?? null,
      );
      setSelectedTripId(saved.id);
      setCompletedAttractionIds([]);
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not open the saved itinerary.");
    } finally {
      setLoadingSavedTrip(false);
    }
  };

  useEffect(() => {
    let active = true;
    getUserTrips()
      .then((trips) => {
        if (!active) return;
        setSavedTrips(trips);
        setLoadingTripList(false);
        const currentTripIsOwned = generated && trips.some((trip) => trip.id === generated.trip_id);
        const target =
          requestedTripId ?? (currentTripIsOwned ? generated.trip_id : undefined) ?? trips[0]?.id;
        if (target !== undefined) {
          setSelectedTripId(target);
          if (!trips.some((trip) => trip.id === target)) {
            if (generated) clearTrip();
            void restoreTrip(target);
          } else if (generated?.trip_id !== target) {
            void restoreTrip(target);
          }
        } else {
          setSelectedTripId(null);
          if (generated) clearTrip();
        }
      })
      .catch((cause) => {
        if (active) {
          setLoadingTripList(false);
          toast.error(cause instanceof Error ? cause.message : "Could not load saved trips.");
        }
      });
    return () => {
      active = false;
    };
    // Store setters are stable; reload when the selected trip or in-memory plan changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedTripId, generated?.trip_id]);
  useEffect(() => {
    if (planningBudget !== null) setRemainingBudget(planningBudget);
  }, [planningBudget]);
  const simulate = async (kind: "rainfall" | "traffic" | "crowding" | "closure") => {
    if (!generated || planningAttractions.length === 0) return;
    setReplanning(true);
    try {
      const previousIds = generated.days.flatMap((day) =>
        day.stops.map((stop) => stop.attraction_id),
      );
      const firstPlannedId = previousIds[0];
      const affected = kind === "closure" && firstPlannedId ? [firstPlannedId] : undefined;
      setScenario(
        await replanScenario(
          generated.trip_id,
          planningAttractions,
          [{ kind, severity: 0.6, ...(affected ? { affected_attraction_ids: affected } : {}) }],
          remainingBudget,
          remainingMinutes,
          previousIds,
          completedAttractionIds,
          planningStartLocation ?? [26.9124, 75.7873],
        ),
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not replan this scenario.");
    } finally {
      setReplanning(false);
    }
  };
  const inspectConditions = async () => {
    if (!generated || planningAttractions.length === 0) return;
    try {
      setConditions(await loadConditions(generated.trip_id, planningAttractions));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not load planning conditions.");
    }
  };
  const assessReliability = async () => {
    if (!generated || planningAttractions.length === 0) return;
    try {
      const plannedIds = new Set(
        generated.days.flatMap((day) => day.stops.map((stop) => stop.attraction_id)),
      );
      const plannedAttractions = planningAttractions.filter((item) => plannedIds.has(item.id));
      if (plannedAttractions.length === 0) {
        toast.error("This itinerary has no scheduled attractions to assess.");
        return;
      }
      setReliability(await simulateReliability(generated.trip_id, plannedAttractions));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not assess itinerary reliability.",
      );
    }
  };
  const sendFeedback = async (rating?: number, skipped = false) => {
    if (!generated || planningAttractions.length === 0) return;
    try {
      await submitPreferenceFeedback(
        generated.trip_id,
        planningAttractions.slice(0, 3).map((item) => ({
          category: item.category,
          ...(rating === undefined ? {} : { rating }),
          skipped,
        })),
      );
      toast.success(
        skipped
          ? "Skipped categories will be down-weighted in future plans."
          : "Your preference profile was updated.",
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save feedback.");
    }
  };
  if (!generated) {
    if (loadingTripList || loadingSavedTrip) {
      return (
        <div className="surface p-6 text-sm text-muted-foreground" role="status">
          Loading your most recent trip…
        </div>
      );
    }
    return (
      <EmptyState
        title="No itinerary open yet."
        description="Create a trip plan to generate an itinerary for your travel dates and preferences."
        action={
          <Button asChild>
            <Link to="/app/planner">Plan a trip</Link>
          </Button>
        }
      />
    );
  }

  const generatedDay = generated.days.map((day) => ({
    day: day.day_number,
    hasStops: day.stops.length > 0,
    city: generatedDestination ?? "Generated itinerary",
    date: `${day.date} · ${generated.data_source} planning data`,
    weather: "Risk estimate",
    temp: `Risk ${((1 - day.stops.reduce((survival, stop) => survival * (1 - stop.risk_score), 1)) * 100).toFixed(0)}%`,
    travelTime: `${day.total_travel_minutes} min`,
    distance: `${day.reserved_break_minutes} min meal/rest time`,
    hotel: "Accommodation is outside this baseline optimizer",
    cost: day.total_cost,
    slots: [
      ...day.stops.map((stop) => ({
        minute: stop.arrival_minute,
        time: `${formatClock(stop.arrival_minute)}–${formatClock(stop.departure_minute)}`,
        attractionId: stop.attraction_id,
        title: stop.name,
        detail: `${stop.departure_minute - stop.arrival_minute} min visit · ${stop.travel_minutes_before} min travel${stop.wait_minutes ? ` · ${stop.wait_minutes} min wait` : ""} · ${Math.round(stop.risk_score * 100)}% estimated disruption risk`,
        cost: stop.cost,
      })),
      ...(day.stops.length > 0 ? day.meal_breaks : []).map((meal) => ({
        minute: meal.start_minute,
        time: `${formatClock(meal.start_minute)}–${formatClock(meal.start_minute + meal.duration_minutes)}`,
        attractionId: undefined,
        title: "Meal and rest break",
        detail: `${meal.duration_minutes} min reserved`,
        cost: 0,
      })),
    ].sort((left, right) => left.minute - right.minute),
  }));
  const budgetEstimate = generated.budget_estimate;
  const total = budgetEstimate?.total_estimated ?? generated.total_cost;
  const displayBreakdown = budgetEstimate?.categories.map((item) => ({
    name: item.label,
    value: item.amount,
    assumptions: item.assumptions,
    source: item.source,
  })) ?? [
    {
      name: "Attraction fees",
      value: generated.total_cost,
      assumptions: [],
      source: generated.data_source,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={
          generatedDestination
            ? `${generatedDestination} baseline itinerary`
            : "Generated itinerary"
        }
        description={`${generated.days.length} days · ${generated.days[0]?.date ?? ""} to ${generated.days.at(-1)?.date ?? ""} · Greedy baseline · ${generated.feasible ? "constraints met" : "incomplete or infeasible"} · ${generated.data_source} attraction data`}
        actions={
          <>
            <Button variant="outline" onClick={() => toast("Editing mode is a demo stub")}>
              <Pencil className="h-4 w-4" /> Edit
            </Button>
            <Button variant="outline" onClick={() => toast.success("Regenerating with AI…")}>
              <RefreshCw className="h-4 w-4" /> Regenerate
            </Button>
            <Button variant="outline" onClick={() => toast.success("PDF export queued")}>
              <Download className="h-4 w-4" /> Download
            </Button>
            <Button onClick={() => toast.success("Share link copied")}>
              <Share2 className="h-4 w-4" /> Share
            </Button>
          </>
        }
      />

      {savedTrips.length > 0 ? (
        <label className="flex flex-wrap items-center gap-3 text-sm">
          Open another saved trip
          <select
            className="min-w-56 rounded-md border border-input bg-background px-3 py-2"
            value={selectedTripId ?? ""}
            disabled={loadingSavedTrip}
            onChange={(event) => {
              const tripId = Number(event.target.value);
              if (!Number.isFinite(tripId)) return;
              setSelectedTripId(tripId);
              void navigate({ search: { tripId } });
            }}
          >
            {savedTrips.map((trip) => (
              <option key={trip.id} value={trip.id}>
                {trip.name} · {trip.start_date}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <ol className="relative space-y-5 border-l border-border pl-6">
          {generated &&
          (generated.warnings.length > 0 ||
            generated.days.some((day) => day.warnings.length > 0)) ? (
            <div className="surface border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
              {[...generated.warnings, ...generated.days.flatMap((day) => day.warnings)].join(" ")}
            </div>
          ) : null}
          {generatedDay.map((day, i) => (
            <motion.li
              key={day.day}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ delay: i * 0.05 }}
              className="relative"
            >
              <span className="absolute -left-[31px] top-5 grid h-6 w-6 place-items-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">
                {day.day}
              </span>
              <article className="surface overflow-hidden">
                <header className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border p-4 sm:flex sm:justify-between">
                  <div className="min-w-0">
                    <h2 className="truncate font-semibold">{day.city}</h2>
                    <p className="text-xs text-muted-foreground">{day.date}</p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs">
                    <Badge variant="secondary">
                      {day.weather === "Sunny" ? (
                        <Sun className="mr-1 h-3 w-3" />
                      ) : (
                        <CloudSun className="mr-1 h-3 w-3" />
                      )}
                      {day.temp}
                    </Badge>
                    <Badge variant="secondary">
                      <Clock className="mr-1 h-3 w-3" /> {day.travelTime}
                    </Badge>
                    <Badge variant="secondary">
                      <Navigation className="mr-1 h-3 w-3" /> {day.distance}
                    </Badge>
                  </div>
                </header>

                <div className="divide-y divide-border">
                  {day.slots.map((slot) => (
                    <div
                      key={`${slot.minute}-${slot.title}`}
                      className="grid gap-1 p-4 sm:grid-cols-[110px_minmax(0,1fr)_auto]"
                    >
                      <span className="text-xs font-semibold tracking-wide text-primary">
                        {slot.time}
                      </span>
                      <div className="min-w-0">
                        <p className="font-medium">
                          {slot.title}
                          {slot.attractionId && completedAttractionIds.includes(slot.attractionId)
                            ? " · completed"
                            : ""}
                        </p>
                        <p className="text-sm text-muted-foreground">{slot.detail}</p>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="shrink-0 text-sm font-medium">
                          ₹{slot.cost.toLocaleString("en-IN")}
                        </span>
                        {slot.attractionId ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              setCompletedAttractionIds((current) =>
                                current.includes(slot.attractionId!)
                                  ? current.filter((id) => id !== slot.attractionId)
                                  : [...current, slot.attractionId!],
                              )
                            }
                          >
                            {completedAttractionIds.includes(slot.attractionId)
                              ? "Undo"
                              : "Completed"}
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  ))}
                  {!day.hasStops ? (
                    <div className="p-4 text-sm text-muted-foreground">
                      No attractions were scheduled for this day. The available catalog or daily
                      time and budget limits did not provide a feasible stop.
                    </div>
                  ) : null}
                </div>

                <footer className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-t border-border bg-muted/40 p-4 text-sm sm:flex sm:justify-between">
                  <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                    <BedDouble className="h-4 w-4 shrink-0" />
                    <span className="truncate">{day.hotel}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1 font-semibold">
                    <Wallet className="h-4 w-4" /> Attraction fees ₹
                    {day.cost.toLocaleString("en-IN")}
                  </span>
                </footer>
              </article>
            </motion.li>
          ))}
        </ol>

        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <div className="surface space-y-2 p-5">
            <div className="p-4">
              <p className="text-sm font-medium">Planned travel time</p>
              <p className="text-xs text-muted-foreground">
                {generated.total_travel_minutes} min across scheduled activities. This is an
                estimate; the baseline may use straight-line routing.
              </p>
            </div>
          </div>

          <div className="surface space-y-3 p-5">
            <h2 className="font-semibold">Budget summary</h2>
            <p className="text-3xl font-semibold tracking-tight">
              ₹{total.toLocaleString("en-IN")}
            </p>
            {budgetEstimate ? (
              <div className="space-y-1 text-xs text-muted-foreground">
                <p>
                  Estimated per person: ₹{budgetEstimate.per_person.toLocaleString("en-IN")} · daily
                  average: ₹{budgetEstimate.daily_average.toLocaleString("en-IN")}
                </p>
                <p>
                  {budgetEstimate.within_budget
                    ? `₹${budgetEstimate.remaining_budget.toLocaleString("en-IN")} estimated remaining`
                    : `₹${Math.abs(budgetEstimate.remaining_budget).toLocaleString("en-IN")} over budget`}
                </p>
                <p>
                  Estimated budget use:{" "}
                  {budgetEstimate.budget_limit > 0
                    ? Math.round(
                        (budgetEstimate.total_estimated / budgetEstimate.budget_limit) * 100,
                      )
                    : 0}
                  % of ₹{budgetEstimate.budget_limit.toLocaleString("en-IN")}
                </p>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Attraction fees only; full trip estimate is not available for this saved plan.
              </p>
            )}
            <div className="space-y-2.5 pt-2">
              {displayBreakdown.map((b) => (
                <div key={b.name} className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">{b.name}</span>
                    <span>₹{b.value.toLocaleString("en-IN")}</span>
                  </div>
                  <Progress value={total > 0 ? (b.value / total) * 100 : 0} className="h-1.5" />
                  <details className="text-[11px] text-muted-foreground">
                    <summary>{b.source} estimate and assumptions</summary>
                    {b.assumptions.map((assumption) => (
                      <p key={assumption} className="mt-1">
                        {assumption}
                      </p>
                    ))}
                  </details>
                </div>
              ))}
            </div>
            {budgetEstimate?.exclusions.map((exclusion) => (
              <p key={exclusion} className="text-[11px] text-muted-foreground">
                {exclusion}
              </p>
            ))}
          </div>
          {generated ? (
            <div className="surface space-y-3 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold">Reliability estimate</h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Seeded disruption scenarios for the selected stops, using their weather, crowd
                    and availability risk inputs ({generated.data_source}).
                  </p>
                </div>
                <Button size="sm" variant="outline" onClick={assessReliability}>
                  Assess
                </Button>
              </div>
              {reliability ? (
                <div className="text-sm">
                  <p className="text-2xl font-semibold">
                    {Math.round(reliability.completion_probability * 100)}%
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Estimated completion probability · {reliability.expected_disruptions.toFixed(2)}{" "}
                    expected disruptions
                  </p>
                </div>
              ) : null}
            </div>
          ) : null}
          {generated ? (
            <div className="surface space-y-3 p-5">
              <div>
                <h2 className="font-semibold">Improve future plans</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Feedback updates category weights for this trip.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => sendFeedback(5)}>
                  Loved it
                </Button>
                <Button size="sm" variant="outline" onClick={() => sendFeedback(3)}>
                  Neutral
                </Button>
                <Button size="sm" variant="outline" onClick={() => sendFeedback(undefined, true)}>
                  Skip similar
                </Button>
              </div>
            </div>
          ) : null}
          {generated ? (
            <div className="surface space-y-3 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold">Planning conditions</h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Risk inputs used by this plan.
                  </p>
                </div>
                <Button size="sm" variant="outline" onClick={inspectConditions}>
                  Inspect
                </Button>
              </div>
              {conditions ? (
                <p className="text-xs text-muted-foreground">
                  Source: <span className="font-medium text-foreground">{conditions.source}</span> ·{" "}
                  {conditions.conditions.length} attraction snapshots
                </p>
              ) : null}
            </div>
          ) : null}
          {alternatives.length > 0 ? (
            <div className="surface space-y-3 p-5">
              <div>
                <h2 className="font-semibold">Pareto alternatives</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  NSGA-II compares attraction selection trade-offs. Time and risk columns are
                  planning proxies; these alternatives are single-day comparisons.
                </p>
              </div>
              {alternatives.map((alternative, index) => (
                <div
                  key={`${alternative.objectives.cost}-${index}`}
                  className="rounded-lg border border-border p-3 text-xs"
                >
                  <p className="font-medium">Option {index + 1}</p>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-muted-foreground">
                    <span>₹{alternative.objectives.cost.toLocaleString("en-IN")}</span>
                    <span>{Math.round(alternative.objectives.time_proxy_minutes)} min</span>
                    <span>Risk {Math.round(alternative.objectives.risk_proxy * 100)}%</span>
                    <span>Utility {alternative.objectives.utility.toFixed(2)}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : null}
          {annealing ? (
            <div className="surface space-y-2 p-5 text-sm">
              <h2 className="font-semibold">Simulated annealing</h2>
              <p className="text-xs text-muted-foreground">
                A one-day alternative selected with a seeded search; these figures are estimates.
              </p>
              <p className="text-muted-foreground">
                ₹{annealing.total_cost.toLocaleString("en-IN")} · {annealing.total_travel_minutes}{" "}
                min · satisfaction {annealing.satisfaction.toFixed(2)} · risk{" "}
                {Math.round(annealing.risk_score * 100)}%
              </p>
            </div>
          ) : null}
          {generated ? (
            <div className="surface space-y-3 p-5">
              <div>
                <h2 className="font-semibold">What-if replanning</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Scenario inputs use synthetic estimates.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {(["rainfall", "traffic", "crowding", "closure"] as const).map((kind) => (
                  <Button
                    key={kind}
                    size="sm"
                    variant="outline"
                    disabled={replanning}
                    onClick={() => simulate(kind)}
                  >
                    {kind}
                  </Button>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <label className="space-y-1 text-muted-foreground">
                  Remaining budget
                  <input
                    className="w-full rounded-md border border-input bg-background px-2 py-1 text-foreground"
                    type="number"
                    min="0"
                    value={remainingBudget}
                    onChange={(event) => setRemainingBudget(Number(event.target.value))}
                  />
                </label>
                <label className="space-y-1 text-muted-foreground">
                  Daily schedule cutoff
                  <input
                    className="w-full rounded-md border border-input bg-background px-2 py-1 text-foreground"
                    type="time"
                    value={formatClock(remainingMinutes)}
                    onChange={(event) => {
                      const [hoursValue, minutesValue] = event.target.value.split(":");
                      const hours = Number(hoursValue);
                      const minutes = Number(minutesValue);
                      if (
                        hoursValue &&
                        minutesValue &&
                        Number.isFinite(hours) &&
                        Number.isFinite(minutes)
                      ) {
                        setRemainingMinutes(hours * 60 + minutes);
                      }
                    }}
                  />
                </label>
              </div>
              {scenario ? (
                <div className="rounded-lg bg-muted p-3 text-xs">
                  <p className="font-medium">Updated remaining plan</p>
                  <p className="mt-1 text-muted-foreground">
                    {scenario.disruptions_applied.join(", ")} · ₹
                    {scenario.total_cost.toLocaleString("en-IN")} · {scenario.total_travel_minutes}{" "}
                    min
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    {scenario.stops.map((stop) => stop.name).join(" → ") || "No eligible stops"}
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    Retained {scenario.retained_planned_attraction_ids.length} planned stops ·{" "}
                    {scenario.change_count} changes
                  </p>
                </div>
              ) : null}
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
