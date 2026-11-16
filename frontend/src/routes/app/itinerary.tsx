import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
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
import { PageHeader } from "@/components/travel/PageHeader";
import { IndiaMap } from "@/components/travel/IndiaMap";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { itinerary, budgetBreakdown } from "@/data/trips";
import { useTripStore } from "@/store/trip";
import {
  loadConditions,
  replanScenario,
  simulateReliability,
  submitPreferenceFeedback,
  type ConditionsResult,
  type ReliabilityResult,
  type ScenarioResult,
} from "@/lib/api";

export const Route = createFileRoute("/app/itinerary")({
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Your Itinerary · GoWander" },
      {
        name: "description",
        content:
          "A day-by-day timeline with morning, afternoon and evening plans, travel time, hotels, weather and cost estimates.",
      },
      { property: "og:title", content: "Your Itinerary · GoWander" },
      {
        property: "og:description",
        content: "AI-generated day-by-day India itinerary with routes, hotels and costs.",
      },
    ],
  }),
  component: Itinerary,
});

function Itinerary() {
  const generated = useTripStore((state) => state.generated);
  const generatedDestination = useTripStore((state) => state.generatedDestination);
  const alternatives = useTripStore((state) => state.alternatives);
  const planningAttractions = useTripStore((state) => state.planningAttractions);
  const annealing = useTripStore((state) => state.annealing);
  const [scenario, setScenario] = useState<ScenarioResult | null>(null);
  const [replanning, setReplanning] = useState(false);
  const [reliability, setReliability] = useState<ReliabilityResult | null>(null);
  const [conditions, setConditions] = useState<ConditionsResult | null>(null);
  const [remainingBudget, setRemainingBudget] = useState(60000);
  const [remainingMinutes, setRemainingMinutes] = useState(720);
  const simulate = async (kind: "rainfall" | "traffic" | "crowding" | "closure") => {
    if (!generated || planningAttractions.length === 0) return;
    setReplanning(true);
    try {
      const affected = kind === "closure" ? [planningAttractions[0]!.id] : undefined;
      const previousIds = generated.days.flatMap((day) =>
        day.stops.map((stop) => stop.attraction_id),
      );
      setScenario(
        await replanScenario(
          generated.trip_id,
          planningAttractions,
          [{ kind, severity: 0.6, ...(affected ? { affected_attraction_ids: affected } : {}) }],
          remainingBudget,
          remainingMinutes,
          previousIds,
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
      setReliability(await simulateReliability(generated.trip_id, planningAttractions));
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
  const generatedDay = generated
    ? generated.days.map((day) => ({
        day: day.day_number,
        city: generatedDestination ?? "Generated itinerary",
        date: `${day.date} · baseline plan · synthetic attraction catalog`,
        weather: "Estimated",
        temp: `Risk ${(generated.risk_score * 100).toFixed(0)}%`,
        travelTime: `${day.total_travel_minutes} min`,
        distance: `${day.reserved_break_minutes} min reserved for meals`,
        hotel: "Accommodation is outside this baseline optimizer",
        cost: day.total_cost,
        slots: day.stops.map((stop) => ({
          time: "Activity" as const,
          title: stop.name,
          detail: `${stop.arrival_minute}–${stop.departure_minute} min · ${stop.travel_minutes_before} min travel${stop.wait_minutes ? ` · ${stop.wait_minutes} min wait` : ""}`,
          cost: stop.cost,
        })),
      }))
    : itinerary;
  const total = generated?.total_cost ?? itinerary.reduce((a, d) => a + d.cost, 0);
  const displayBreakdown = generated
    ? [{ name: "Attractions", value: generated.total_cost, color: "var(--color-chart-1)" }]
    : budgetBreakdown;

  return (
    <div className="space-y-6">
      <PageHeader
        title={
          generatedDestination
            ? `${generatedDestination} baseline itinerary`
            : "Royal Rajasthan Loop"
        }
        description={
          generated
            ? `Greedy baseline · ${generated.feasible ? "feasible" : "infeasible"} · ${generated.data_source} inputs`
            : "4 days · Jaipur → Udaipur → Kumbhalgarh · generated 2 hours ago"
        }
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
                      key={slot.time}
                      className="grid gap-1 p-4 sm:grid-cols-[110px_minmax(0,1fr)_auto]"
                    >
                      <span className="text-xs font-semibold uppercase tracking-wide text-primary">
                        {slot.time}
                      </span>
                      <div className="min-w-0">
                        <p className="font-medium">{slot.title}</p>
                        <p className="text-sm text-muted-foreground">{slot.detail}</p>
                      </div>
                      <span className="shrink-0 text-sm font-medium">
                        ₹{slot.cost.toLocaleString("en-IN")}
                      </span>
                    </div>
                  ))}
                </div>

                <footer className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-t border-border bg-muted/40 p-4 text-sm sm:flex sm:justify-between">
                  <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                    <BedDouble className="h-4 w-4 shrink-0" />
                    <span className="truncate">{day.hotel}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1 font-semibold">
                    <Wallet className="h-4 w-4" /> ₹{day.cost.toLocaleString("en-IN")}
                  </span>
                </footer>
              </article>
            </motion.li>
          ))}
        </ol>

        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <div className="surface overflow-hidden">
            <div className="h-48">
              <IndiaMap showRoutes className="rounded-none" />
            </div>
            <div className="p-4">
              <p className="text-sm font-medium">Route preview</p>
              <p className="text-xs text-muted-foreground">712 km total · 9h 05m driving</p>
            </div>
          </div>

          <div className="surface space-y-3 p-5">
            <h2 className="font-semibold">Budget summary</h2>
            <p className="text-3xl font-semibold tracking-tight">
              ₹{total.toLocaleString("en-IN")}
            </p>
            <p className="text-xs text-muted-foreground">Estimated for 2 travellers</p>
            <div className="space-y-2.5 pt-2">
              {displayBreakdown.map((b) => (
                <div key={b.name} className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">{b.name}</span>
                    <span>₹{b.value.toLocaleString("en-IN")}</span>
                  </div>
                  <Progress
                    value={(b.value / displayBreakdown[0]!.value) * 100}
                    className="h-1.5"
                  />
                </div>
              ))}
            </div>
          </div>
          {generated ? (
            <div className="surface space-y-3 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold">Reliability estimate</h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    1,000 seeded synthetic disruption scenarios.
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
                  NSGA-II trade-offs from the same synthetic inputs.
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
                  Available minutes
                  <input
                    className="w-full rounded-md border border-input bg-background px-2 py-1 text-foreground"
                    type="number"
                    min="1"
                    value={remainingMinutes}
                    onChange={(event) => setRemainingMinutes(Number(event.target.value))}
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
