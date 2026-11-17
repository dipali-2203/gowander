import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ArrowLeft, Copy, Pencil, RefreshCw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/travel/PageHeader";
import { Button } from "@/components/ui/button";
import { riskAssessmentLabel, riskDetailsLabel, riskProxyLabel } from "@/lib/risk-display.js";
import {
  deleteTrip,
  duplicateTrip,
  getTrip,
  regenerateTrip,
  updateTrip,
  type TripDetails,
  type TripPlanningOptions,
} from "@/lib/api";

export const Route = createFileRoute("/app/trips/$tripId")({
  validateSearch: (search: Record<string, unknown>) => ({
    edit: search["edit"] === "1" || search["edit"] === true,
  }),
  component: TripDetailsPage,
});

function clock(minute: number) {
  return `${String(Math.floor(minute / 60) % 24).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
}

function TripDetailsPage() {
  const { tripId: rawTripId } = Route.useParams();
  const { edit } = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  const tripId = Number(rawTripId);
  const [trip, setTrip] = useState<TripDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(edit);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    origin: "",
    destination: "",
    startDate: "",
    endDate: "",
    budget: "",
    travelers: "1",
    transport: "mixed",
    accommodation: "standard" as TripPlanningOptions["accommodation_category"],
    mealPreferences: "",
    miscellaneous: "0",
    dailyCutoff: "20:00",
    interests: "",
  });

  useEffect(() => setEditing(edit), [edit]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const saved = await getTrip(tripId);
      setTrip(saved);
      setForm({
        name: saved.name,
        origin: saved.origin,
        destination: saved.destination,
        startDate: saved.start_date,
        endDate: saved.end_date,
        budget: String(saved.budget),
        travelers: String(saved.planning_options.traveler_count),
        transport: saved.planning_options.transportation_mode,
        accommodation: saved.planning_options.accommodation_category,
        mealPreferences: saved.planning_options.meal_preferences.join(", "),
        miscellaneous: String(saved.planning_options.miscellaneous_budget),
        dailyCutoff: clock(saved.available_minutes_per_day),
        interests: Object.keys(
          (saved.preferences["interests"] ?? {}) as Record<string, unknown>,
        ).join(", "),
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load this trip.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // Load only when the route ID changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tripId]);

  const save = async (replaceItinerary = false) => {
    if (!trip) return;
    setBusy(true);
    try {
      const interests = Object.fromEntries(
        form.interests
          .split(",")
          .map((value) => value.trim().toLowerCase())
          .filter(Boolean)
          .map((value) => [value, 1]),
      );
      await updateTrip(trip.id, {
        name: form.name.trim(),
        origin: form.origin.trim(),
        destination: form.destination.trim(),
        start_date: form.startDate,
        end_date: form.endDate,
        budget: Number(form.budget),
        available_minutes_per_day:
          Number(form.dailyCutoff.slice(0, 2)) * 60 + Number(form.dailyCutoff.slice(3, 5)),
        preferences: { ...trip.preferences, interests },
        planning_options: {
          traveler_count: Number(form.travelers),
          transportation_mode: form.transport,
          accommodation_category: form.accommodation,
          meal_preferences: form.mealPreferences
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
          miscellaneous_budget: Number(form.miscellaneous),
        },
      });
      const updated = await getTrip(trip.id);
      setTrip(updated);
      setEditing(false);
      await navigate({ search: { edit: false } });
      if (replaceItinerary) {
        try {
          const itinerary = await regenerateTrip(trip.id);
          setTrip({
            ...updated,
            latest_itinerary: itinerary,
            itinerary_stale: false,
            optimization_results: {},
          });
          toast.success("Trip details saved and a replacement itinerary was generated.");
        } catch (cause) {
          toast.error(
            cause instanceof Error
              ? `Trip details saved, but regeneration failed: ${cause.message}`
              : "Trip details saved, but regeneration failed.",
          );
        }
      } else {
        toast.success(
          "Trip details saved. The previous itinerary remains available until you regenerate it.",
        );
      }
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not save trip details.");
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    if (!trip) return;
    setBusy(true);
    try {
      const itinerary = await regenerateTrip(trip.id);
      setTrip({
        ...trip,
        latest_itinerary: itinerary,
        itinerary_stale: false,
        optimization_results: {},
      });
      toast.success("A replacement itinerary was generated and saved.");
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not regenerate this itinerary.");
    } finally {
      setBusy(false);
    }
  };

  const duplicate = async () => {
    if (!trip) return;
    setBusy(true);
    try {
      const copied = await duplicateTrip(trip.id);
      await navigate({
        to: "/app/trips/$tripId",
        params: { tripId: String(copied.id) },
        search: { edit: false },
      });
      toast.success("Trip duplicated.");
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not duplicate this trip.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!trip || !window.confirm(`Delete “${trip.name}”? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await deleteTrip(trip.id);
      await navigate({ to: "/app/saved" });
      toast.success("Trip deleted.");
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not delete this trip.");
    } finally {
      setBusy(false);
    }
  };

  if (loading)
    return <div className="surface p-6 text-sm text-muted-foreground">Loading trip…</div>;
  if (error || !trip)
    return (
      <div className="surface p-6 text-sm text-destructive" role="alert">
        {error ?? "Trip not found."}
      </div>
    );

  const itinerary = trip.latest_itinerary as
    | (TripDetails["latest_itinerary"] & {
        days?: Array<{
          day_number: number;
          date: string;
          stops: Array<{
            attraction_id: string;
            name: string;
            arrival_minute: number;
            departure_minute: number;
            travel_minutes_before: number;
            cost: number;
            risk_score: number | null;
            risk_data_status?: string;
          }>;
          meal_breaks: Array<{ start_minute: number; duration_minutes: number }>;
          total_cost: number;
          total_travel_minutes: number;
          warnings: string[];
          feasible: boolean;
        }>;
      })
    | null;
  const hasDaySchedule = Array.isArray(itinerary?.days);
  const attributions = [
    ...new Set(
      (trip.planning_inputs?.attractions ?? [])
        .map((item) => item.attribution)
        .filter((value): value is string => Boolean(value)),
    ),
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={trip.name || trip.destination}
        description={`${trip.origin || "Starting location not specified"} → ${trip.destination} · ${trip.start_date} to ${trip.end_date}`}
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/app/saved">
                <ArrowLeft className="h-4 w-4" /> Saved trips
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/app/itinerary" search={{ tripId: trip.id }}>
                Open itinerary
              </Link>
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                const next = !editing;
                setEditing(next);
                void navigate({ search: { edit: next } });
              }}
            >
              <Pencil className="h-4 w-4" /> {editing ? "Cancel edit" : "Edit trip"}
            </Button>
            <Button variant="outline" disabled={busy} onClick={duplicate}>
              <Copy className="h-4 w-4" /> Duplicate
            </Button>
            <Button variant="destructive" disabled={busy} onClick={remove}>
              <Trash2 className="h-4 w-4" /> Delete
            </Button>
          </>
        }
      />

      {attributions.map((attribution) => (
        <p key={attribution} className="text-xs text-muted-foreground">
          Attraction data attribution: {attribution}
        </p>
      ))}

      {trip.itinerary_stale ? (
        <div
          className="surface border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"
          role="status"
        >
          Trip inputs have changed. The saved itinerary below is the previous version and remains
          available until a replacement is generated.
        </div>
      ) : null}

      {editing ? (
        <section className="surface space-y-4 p-5">
          <h2 className="font-semibold">Edit trip details</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Trip name"
              value={form.name}
              onChange={(value) => setForm({ ...form, name: value })}
            />
            <Field
              label="Starting city"
              value={form.origin}
              onChange={(value) => setForm({ ...form, origin: value })}
            />
            <Field
              label="Destination"
              value={form.destination}
              onChange={(value) => setForm({ ...form, destination: value })}
            />
            <Field
              label="Total budget (INR)"
              type="number"
              value={form.budget}
              onChange={(value) => setForm({ ...form, budget: value })}
            />
            <Field
              label="Start date"
              type="date"
              value={form.startDate}
              onChange={(value) => setForm({ ...form, startDate: value })}
            />
            <Field
              label="End date"
              type="date"
              value={form.endDate}
              onChange={(value) => setForm({ ...form, endDate: value })}
            />
            <Field
              label="Travelers"
              type="number"
              value={form.travelers}
              onChange={(value) => setForm({ ...form, travelers: value })}
            />
            <label className="space-y-1 text-sm">
              Daily schedule cutoff
              <input
                className="w-full rounded-md border border-input bg-background px-3 py-2"
                type="time"
                value={form.dailyCutoff}
                onChange={(event) => setForm({ ...form, dailyCutoff: event.target.value })}
              />
            </label>
            <label className="space-y-1 text-sm">
              Transportation
              <select
                className="w-full rounded-md border border-input bg-background px-3 py-2"
                value={form.transport}
                onChange={(event) => setForm({ ...form, transport: event.target.value })}
              >
                {[
                  "walking",
                  "public transport",
                  "bus",
                  "train",
                  "taxi",
                  "car",
                  "rental vehicle",
                  "mixed",
                ].map((mode) => (
                  <option key={mode} value={mode}>
                    {mode}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              Accommodation category
              <select
                className="w-full rounded-md border border-input bg-background px-3 py-2"
                value={form.accommodation}
                onChange={(event) =>
                  setForm({
                    ...form,
                    accommodation: event.target
                      .value as TripPlanningOptions["accommodation_category"],
                  })
                }
              >
                {["budget", "standard", "premium", "luxury"].map((category) => (
                  <option key={category}>{category}</option>
                ))}
              </select>
            </label>
            <Field
              label="Meal preferences (comma-separated)"
              value={form.mealPreferences}
              onChange={(value) => setForm({ ...form, mealPreferences: value })}
            />
            <Field
              label="Miscellaneous estimate (INR)"
              type="number"
              value={form.miscellaneous}
              onChange={(value) => setForm({ ...form, miscellaneous: value })}
            />
            <Field
              label="Travel interests (comma-separated)"
              value={form.interests}
              onChange={(value) => setForm({ ...form, interests: value })}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy} onClick={() => void save()}>
              <Save className="h-4 w-4" /> Save changes
            </Button>
            <Button
              variant="outline"
              disabled={busy || !trip.planning_inputs}
              onClick={() => void save(true)}
            >
              <RefreshCw className="h-4 w-4" /> Save and regenerate
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Saving edits does not replace the current itinerary. Regeneration uses the saved
            attraction data and new trip constraints. This does not geocode a changed starting city
            or destination.
          </p>
        </section>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Summary label="Dates" value={`${trip.start_date} – ${trip.end_date}`} />
        <Summary label="Travelers" value={String(trip.planning_options.traveler_count)} />
        <Summary label="Trip budget" value={`₹${trip.budget.toLocaleString("en-IN")}`} />
        <Summary label="Transportation" value={trip.planning_options.transportation_mode} />
        <Summary
          label="Accommodation preference"
          value={trip.planning_options.accommodation_category}
        />
        <Summary
          label="Meal preferences"
          value={trip.planning_options.meal_preferences.join(", ") || "Not specified"}
        />
        <Summary
          label="Interests"
          value={
            Object.keys((trip.preferences["interests"] ?? {}) as Record<string, unknown>).join(
              ", ",
            ) || "Not specified"
          }
        />
        <Summary
          label="Itinerary"
          value={
            hasDaySchedule
              ? `${itinerary.days!.length} days saved`
              : trip.latest_itinerary
                ? "Legacy saved plan"
                : "Not generated"
          }
        />
        <Summary
          label="Baseline optimizer"
          value={trip.latest_itinerary?.algorithm ?? "Not generated"}
        />
        <Summary
          label="Plan risk estimate"
          value={
            trip.latest_itinerary
              ? `${riskAssessmentLabel(trip.latest_itinerary.risk_score, trip.latest_itinerary.risk_data_status)} · ${trip.latest_itinerary.data_source}`
              : "Unavailable"
          }
        />
      </section>

      {hasDaySchedule ||
      trip.optimization_results.pareto?.length ||
      trip.optimization_results.simulated_annealing ? (
        <details className="surface p-4">
          <summary className="cursor-pointer font-semibold">Advanced Optimization Insights</summary>
          <div className="mt-4 space-y-4">
            {trip.optimization_results.pareto?.length ||
            trip.optimization_results.simulated_annealing ? (
              <section className="surface space-y-3 p-5">
                <h2 className="font-semibold">Saved single-day optimization alternatives</h2>
                <p className="text-xs text-muted-foreground">
                  These are one-day comparisons, not replacements for this multi-day itinerary.
                  Pareto time and risk values are planning proxies, not live measurements.
                </p>
                {trip.optimization_results.pareto?.map((alternative, index) => (
                  <div key={index} className="rounded-lg border border-border p-3 text-sm">
                    <p className="font-medium">Pareto option {index + 1}</p>
                    <p className="mt-1 text-muted-foreground">
                      ₹{alternative.objectives.cost.toLocaleString("en-IN")} ·{" "}
                      {Math.round(alternative.objectives.time_proxy_minutes)} min proxy ·{" "}
                      {riskProxyLabel(
                        alternative.objectives.risk_proxy,
                        alternative.risk_data_status,
                      )}{" "}
                      · utility {alternative.objectives.utility.toFixed(2)}
                    </p>
                  </div>
                ))}
                {trip.optimization_results.simulated_annealing ? (
                  <p className="text-sm text-muted-foreground">
                    Single-day simulated annealing · ₹
                    {trip.optimization_results.simulated_annealing.total_cost.toLocaleString(
                      "en-IN",
                    )}{" "}
                    attraction fees ·{" "}
                    {trip.optimization_results.simulated_annealing.total_travel_minutes} min
                    estimated travel ·{" "}
                    {trip.optimization_results.simulated_annealing.feasible
                      ? "feasible"
                      : "incomplete"}
                  </p>
                ) : null}
              </section>
            ) : null}
            {hasDaySchedule ? (
              <section
                className="surface space-y-2 p-3 text-xs"
                aria-label="Saved itinerary assumptions"
              >
                <h2 className="font-medium">Planning conditions and warnings</h2>
                <p className="text-sm text-muted-foreground">
                  Some attraction details, risk assessments and transfer times are estimated or
                  unavailable. Verify important details before travelling.
                </p>
                <p className="text-muted-foreground">
                  Risk data: {itinerary?.risk_data_status ?? "unavailable"}. Risk tolerance cannot
                  be fully applied when observations are missing.
                </p>
                <details>
                  <summary className="cursor-pointer font-medium">
                    View individual risk assessments and warnings
                  </summary>
                  <ul className="mt-2 list-inside list-disc space-y-1 text-muted-foreground">
                    {itinerary?.days
                      ?.flatMap((day) => day.stops)
                      .map((stop) => (
                        <li key={stop.attraction_id}>
                          {stop.name}:{" "}
                          {riskDetailsLabel(
                            stop.risk_score,
                            stop.risk_data_status,
                            trip.planning_inputs?.attractions.find(
                              (item) => item.id === stop.attraction_id,
                            )?.risk_metadata,
                          )}
                        </li>
                      ))}
                    {[...new Set(itinerary?.days?.flatMap((day) => day.warnings) ?? [])].map(
                      (warning) => (
                        <li key={warning}>{warning}</li>
                      ),
                    )}
                  </ul>
                </details>
              </section>
            ) : null}
          </div>
        </details>
      ) : null}

      {hasDaySchedule ? (
        <section className="space-y-4">
          <h2 className="text-lg font-semibold">Saved itinerary</h2>
          <section
            className="surface space-y-2 p-3 text-xs"
            aria-label="Saved itinerary assumptions"
          >
            <p className="text-sm text-muted-foreground">
              Some attraction details, risk assessments and transfer times are estimated or
              unavailable. Verify important details before travelling.
            </p>
            <p className="text-muted-foreground">
              Risk data: {itinerary?.risk_data_status ?? "unavailable"}. Risk tolerance cannot be
              fully applied when observations are missing.
            </p>
          </section>
          {itinerary.days!.map((day) => (
            <article key={day.day_number} className="surface space-y-3 p-5">
              <header className="flex flex-wrap justify-between gap-2">
                <h3 className="font-semibold">
                  Day {day.day_number} · {day.date}
                </h3>
                <p className="text-sm text-muted-foreground">
                  Attraction fees ₹{day.total_cost.toLocaleString("en-IN")} ·{" "}
                  {day.total_travel_minutes} min estimated travel
                </p>
              </header>
              {day.stops.length ? (
                <ol className="space-y-2">
                  {day.stops.map((stop) => (
                    <li key={stop.attraction_id} className="rounded-lg bg-muted/50 p-3">
                      <p className="font-medium">
                        {clock(stop.arrival_minute)}–{clock(stop.departure_minute)} · {stop.name}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {stop.travel_minutes_before} min estimated travel ·{" "}
                        {stop.departure_minute - stop.arrival_minute} min{" "}
                        {trip.planning_inputs?.attractions.find(
                          (item) => item.id === stop.attraction_id,
                        )?.visit_duration_known === false
                          ? "planned (duration unknown; estimate)"
                          : "visit"}{" "}
                        · ₹{stop.cost.toLocaleString("en-IN")} attraction fee
                        {stop.wait_minutes
                          ? ` · ${stop.wait_minutes} min waiting${stop.wait_reason ? ` — ${stop.wait_reason}` : ""}`
                          : ""}
                      </p>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No activities were scheduled for this day.
                </p>
              )}
              {day.meal_breaks?.map((meal) => (
                <p key={meal.start_minute} className="text-sm text-muted-foreground">
                  Meal/rest break {clock(meal.start_minute)} · {meal.duration_minutes} min
                </p>
              ))}
            </article>
          ))}
        </section>
      ) : (
        <section className="surface p-5">
          <h2 className="font-semibold">Itinerary</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {trip.latest_itinerary
              ? "This trip has a saved itinerary in an older format."
              : "No itinerary has been generated for this trip yet."}
          </p>
          {trip.planning_inputs ? (
            <Button className="mt-4" disabled={busy} onClick={regenerate}>
              <RefreshCw className="h-4 w-4" /> Generate itinerary
            </Button>
          ) : null}
        </section>
      )}

      {itinerary?.budget_estimate ? (
        <section className="surface space-y-4 p-5">
          <div>
            <h2 className="font-semibold">Estimated destination expenses</h2>
            <p className="text-xs text-muted-foreground">
              Partial destination estimate, not the complete cost of travelling or live hotel and
              meal quotes. Currency: INR.
            </p>
            {itinerary.budget_estimate.unknown_attraction_fee_count > 0 ? (
              <p className="text-xs font-medium text-amber-700">
                {itinerary.budget_estimate.unknown_attraction_fee_count} scheduled attraction fee(s)
                are unknown. Their internal zero-cost placeholders do not mean entry is free.
              </p>
            ) : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-4">
            <Summary
              label="Estimated destination expenses"
              value={`₹${itinerary.budget_estimate.total_estimated.toLocaleString("en-IN")}`}
            />
            <Summary
              label="Per person"
              value={`₹${itinerary.budget_estimate.per_person.toLocaleString("en-IN")}`}
            />
            <Summary
              label="Daily average"
              value={`₹${itinerary.budget_estimate.daily_average.toLocaleString("en-IN")}`}
            />
            <Summary
              label="Budget status"
              value={
                itinerary.budget_estimate.within_budget
                  ? `Listed estimates below budget · ${Math.round((itinerary.budget_estimate.total_estimated / itinerary.budget_estimate.budget_limit) * 100)}%`
                  : `Listed estimates above budget · ${Math.round((itinerary.budget_estimate.total_estimated / itinerary.budget_estimate.budget_limit) * 100)}%`
              }
            />
          </div>
          <div className="divide-y divide-border">
            {itinerary.budget_estimate.categories.map((category) => (
              <details key={category.key} className="py-3">
                <summary className="flex cursor-pointer justify-between gap-3 text-sm">
                  <span>
                    {category.label} · {category.source}
                  </span>
                  <strong>₹{category.amount.toLocaleString("en-IN")}</strong>
                </summary>
                <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                  {category.assumptions.map((assumption) => (
                    <p key={assumption}>{assumption}</p>
                  ))}
                  <p>
                    Estimate range: ₹{category.range_min.toLocaleString("en-IN")}–₹
                    {category.range_max.toLocaleString("en-IN")}
                  </p>
                </div>
              </details>
            ))}
          </div>
          <div
            className="space-y-1 rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground"
            role="note"
            aria-label="Budget exclusions"
          >
            <p className="font-medium text-foreground">Excluded costs and estimate limits</p>
            {itinerary.budget_estimate.exclusions.map((item) => (
              <p key={item}>{item}</p>
            ))}
          </div>
        </section>
      ) : null}

      <section className="grid gap-4 md:grid-cols-3">
        <UnavailableCard
          title="Accommodation"
          detail="No hotel inventory or live availability provider is configured. This trip stores your preferred category, but does not claim a property or price."
        />
        <UnavailableCard
          title="Restaurants and meals"
          detail="No restaurant or menu-price provider is configured. Meal preferences are saved; recommendations and prices are not fabricated."
        />
        <UnavailableCard
          title="Transport and total cost"
          detail="When available, the budget uses configurable local fare estimates plus hotel and meal allowances. Intercity fares and live prices are unavailable; inspect the assumptions in the budget breakdown."
        />
      </section>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <label className="space-y-1 text-sm">
      {label}
      <input
        className="w-full rounded-md border border-input bg-background px-3 py-2"
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-medium capitalize">{value}</p>
    </div>
  );
}

function UnavailableCard({ title, detail }: { title: string; detail: string }) {
  return (
    <article className="surface space-y-2 p-5">
      <h2 className="font-semibold">{title}</h2>
      <p className="text-sm text-muted-foreground">{detail}</p>
    </article>
  );
}
