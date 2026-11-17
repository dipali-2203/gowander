import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import {
  Sun,
  CloudSun,
  Cloud,
  CloudDrizzle,
  CloudRain,
  CloudSnow,
  CloudFog,
  CloudLightning,
  Clock,
  Navigation,
  BedDouble,
  Wallet,
  Download,
  Share2,
} from "lucide-react";
import { toast } from "sonner";
import { EmptyState, PageHeader } from "@/components/travel/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTripStore } from "@/store/trip";
import { riskAssessmentLabel, riskDetailsLabel, riskProxyLabel } from "@/lib/risk-display.js";
import { readableErrorMessage } from "@/lib/error-message.js";
import {
  getTrip,
  getUserTrips,
  replanScenario,
  proposeWeatherReplan,
  saveCompletedActivities,
  acceptWeatherReplan,
  rejectWeatherReplan,
  downloadTripPdf,
  createTripShareLink,
  revokeTripShareLink,
  simulateReliability,
  submitPreferenceFeedback,
  type ReliabilityResult,
  type ScenarioResult,
  type AccountTrip,
  type WeatherReplanProposal,
  type WeatherRiskAssessment,
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

function formatForecastTimestamp(value: string | null | undefined) {
  if (!value) return null;
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const date = new Date(hasOffset ? value : `${value}+05:30`);
  if (Number.isNaN(date.getTime())) return value;
  return `${new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(date)} IST`;
}

function WeatherConditionIcon({ kind }: { kind: WeatherRiskAssessment["condition_kind"] }) {
  const Icon =
    kind === "sun"
      ? Sun
      : kind === "partly_cloudy"
        ? CloudSun
        : kind === "fog"
          ? CloudFog
          : kind === "drizzle"
            ? CloudDrizzle
            : kind === "rain"
              ? CloudRain
              : kind === "snow"
                ? CloudSnow
                : kind === "thunderstorm"
                  ? CloudLightning
                  : Cloud;
  return <Icon aria-hidden="true" className="h-5 w-5 shrink-0 text-primary" />;
}

function WeatherForecastCard({
  item,
}: {
  item: { name: string; scheduled_time: string | null; risk: WeatherRiskAssessment };
}) {
  const values = item.risk.variables;
  const readings: Array<[string, number | undefined, string]> = [
    ["Temperature", values.temperature_2m, "°C"],
    ["Feels like", values.apparent_temperature, "°C"],
    ["Rain probability", values.precipitation_probability, "%"],
    ["Expected precipitation", values.precipitation, " mm"],
    ["Wind", values.wind_speed_10m, " km/h"],
  ];
  const hasReadings = readings.some(([, value]) => value !== undefined && value !== null);
  const forecastTime = formatForecastTimestamp(item.scheduled_time ?? item.risk.forecast_time);
  return (
    <article className="min-w-0 rounded-md border border-border p-3">
      <div className="flex items-center gap-2">
        <WeatherConditionIcon kind={item.risk.condition_kind} />
        <div className="min-w-0">
          <h3 className="break-words text-sm font-medium">{item.name}</h3>
          <p className="flex flex-wrap gap-x-1 text-xs text-muted-foreground">
            {item.risk.condition ?? "Condition unavailable"}
            {forecastTime ? <span>· {forecastTime}</span> : null}
          </p>
        </div>
      </div>
      {hasReadings ? (
        <dl
          className="mt-3 grid gap-x-3 gap-y-2 text-xs"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 7.5rem), 1fr))" }}
        >
          {readings.map(([label, value, unit]) =>
            value === undefined || value === null ? null : (
              <div key={label} className="min-w-0">
                <dt className="break-words leading-4 text-muted-foreground">{label}</dt>
                <dd className="whitespace-nowrap font-medium">
                  {value}
                  {unit}
                </dd>
              </div>
            ),
          )}
        </dl>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          Weather information unavailable for this activity.
        </p>
      )}
      {item.risk.advisories.map((advisory, index) => (
        <div
          key={`${advisory.type}-${index}`}
          className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-950"
        >
          <p className="font-medium">{advisoryLabel(advisory.type)}</p>
          <p>{advisory.description}</p>
        </div>
      ))}
    </article>
  );
}

function advisoryLabel(type: string) {
  return (
    (
      {
        rain: "Rain advisory",
        precipitation: "Precipitation advisory",
        temperature: "Temperature advisory",
        wind: "Wind advisory",
        weather_condition: "Severe weather advisory",
      } as Record<string, string>
    )[type] ?? "Weather advisory"
  );
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
  const [remainingBudget, setRemainingBudget] = useState(60000);
  const [remainingMinutes, setRemainingMinutes] = useState(1200);
  const [completedAttractionIds, setCompletedAttractionIds] = useState<string[]>([]);
  const [savedTrips, setSavedTrips] = useState<AccountTrip[]>([]);
  const [selectedTripId, setSelectedTripId] = useState<number | null>(generated?.trip_id ?? null);
  const [loadingTripList, setLoadingTripList] = useState(true);
  const [loadingSavedTrip, setLoadingSavedTrip] = useState(false);
  const [itineraryRevision, setItineraryRevision] = useState(0);
  const itineraryRevisionsByTrip = useRef(new Map<number, number>());
  const [weatherProposal, setWeatherProposal] = useState<WeatherReplanProposal | null>(null);
  const [weatherUnavailableDay, setWeatherUnavailableDay] = useState<number | null>(null);
  const [shareDialogOpen, setShareDialogOpen] = useState(false);
  const [shareUrl, setShareUrl] = useState("");
  const [shareBusy, setShareBusy] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const resolvedWeatherProposalIds = useRef(new Set<string>());
  const restorePendingWeatherProposal = (
    proposal: WeatherReplanProposal | null,
    tripId: number,
  ) => {
    if (
      proposal &&
      (resolvedWeatherProposalIds.current.has(proposal.proposal_id) ||
        proposal.base_revision < (itineraryRevisionsByTrip.current.get(tripId) ?? 0))
    )
      return;
    setWeatherProposal(proposal);
  };

  const restoreTrip = async (tripId: number) => {
    setLoadingSavedTrip(true);
    try {
      const saved = await getTrip(tripId);
      const itinerary = saved.latest_itinerary;
      if (!itinerary || !Array.isArray(itinerary.days)) {
        throw new Error("This saved trip does not have a multi-day itinerary yet.");
      }
      if (saved.itinerary_revision < (itineraryRevisionsByTrip.current.get(saved.id) ?? 0)) return;
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
      itineraryRevisionsByTrip.current.set(saved.id, saved.itinerary_revision);
      setItineraryRevision(saved.itinerary_revision);
      setCompletedAttractionIds(saved.completed_attraction_ids ?? []);
      restorePendingWeatherProposal(saved.pending_itinerary_revision ?? null, saved.id);
      setWeatherUnavailableDay(null);
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
          const savedState = trips.find((trip) => trip.id === target);
          if (savedState) {
            if (
              savedState.itinerary_revision >= (itineraryRevisionsByTrip.current.get(target) ?? 0)
            ) {
              itineraryRevisionsByTrip.current.set(target, savedState.itinerary_revision);
              setItineraryRevision(savedState.itinerary_revision);
              setCompletedAttractionIds(savedState.completed_attraction_ids ?? []);
              restorePendingWeatherProposal(savedState.pending_itinerary_revision ?? null, target);
            }
          }
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
      toast.error(readableErrorMessage(error, "Could not replan this scenario."));
    } finally {
      setReplanning(false);
    }
  };
  const checkWeatherForDay = async (dayNumber: number) => {
    if (!generated || !selectedTripId) return;
    setReplanning(true);
    try {
      const proposal = await proposeWeatherReplan(selectedTripId, dayNumber);
      restorePendingWeatherProposal(proposal, selectedTripId);
      setWeatherUnavailableDay(null);
      if (!proposal.forecast_available)
        toast.message("Weather information unavailable for this day.");
    } catch (error) {
      setWeatherProposal(null);
      setWeatherUnavailableDay(dayNumber);
      toast.error(readableErrorMessage(error, "Could not check the forecast."));
    } finally {
      setReplanning(false);
    }
  };
  const exportPdf = async () => {
    if (!selectedTripId) return;
    setDownloadingPdf(true);
    try {
      await downloadTripPdf(selectedTripId);
      toast.success("Your latest saved itinerary PDF is ready.");
    } catch (error) {
      toast.error(readableErrorMessage(error, "Could not download the itinerary PDF."));
    } finally {
      setDownloadingPdf(false);
    }
  };
  const generateShareLink = async () => {
    if (!selectedTripId) return;
    setShareBusy(true);
    try {
      const result = await createTripShareLink(selectedTripId);
      const url = new URL(`/shared/${encodeURIComponent(result.token)}`, window.location.origin);
      setShareUrl(url.toString());
      toast.success(
        result.reused ? "Existing share link loaded." : "Read-only share link created.",
      );
    } catch (error) {
      toast.error(readableErrorMessage(error, "Could not create a share link."));
    } finally {
      setShareBusy(false);
    }
  };
  const copyShareLink = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast.success("Share link copied.");
    } catch {
      toast.error("Clipboard access is unavailable. Select and copy the link from the field.");
    }
  };
  const revokeShareLink = async () => {
    if (!selectedTripId || !shareUrl) return;
    setShareBusy(true);
    try {
      await revokeTripShareLink(selectedTripId);
      setShareUrl("");
      toast.success("Share link revoked.");
    } catch (error) {
      toast.error(readableErrorMessage(error, "Could not revoke the share link."));
    } finally {
      setShareBusy(false);
    }
  };
  const toggleCompleted = async (attractionId: string) => {
    if (!generated || !selectedTripId) return;
    const next = completedAttractionIds.includes(attractionId)
      ? completedAttractionIds.filter((id) => id !== attractionId)
      : [...completedAttractionIds, attractionId];
    try {
      const saved = await saveCompletedActivities(selectedTripId, next, itineraryRevision);
      setCompletedAttractionIds(saved.completed_attraction_ids);
      setWeatherProposal(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save completed activity.");
    }
  };
  const acceptProposal = async () => {
    if (!selectedTripId || !weatherProposal) return;
    try {
      const saved = await acceptWeatherReplan(selectedTripId, weatherProposal);
      setGenerated(
        saved.latest_itinerary,
        generatedDestination ?? "Saved trip",
        alternatives,
        planningAttractions,
        planningStartLocation ?? [26.9124, 75.7873],
        planningBudget ?? 0,
        annealing,
      );
      itineraryRevisionsByTrip.current.set(selectedTripId, saved.itinerary_revision);
      setItineraryRevision(saved.itinerary_revision);
      setCompletedAttractionIds(saved.completed_attraction_ids);
      resolvedWeatherProposalIds.current.add(weatherProposal.proposal_id);
      setWeatherProposal(null);
      toast.success("Itinerary updated based on the weather forecast.");
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not accept the proposed revision.",
      );
    }
  };
  const rejectProposal = async () => {
    if (!selectedTripId || !weatherProposal) return;
    try {
      await rejectWeatherReplan(selectedTripId, weatherProposal);
      resolvedWeatherProposalIds.current.add(weatherProposal.proposal_id);
      setWeatherProposal(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not dismiss the proposal.");
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
    temp:
      day.stops.length &&
      day.stops.every(
        (stop) =>
          typeof stop.risk_score === "number" &&
          stop.risk_data_status &&
          stop.risk_data_status !== "unavailable" &&
          stop.risk_data_status !== "partial",
      )
        ? riskAssessmentLabel(
            1 - day.stops.reduce((survival, stop) => survival * (1 - (stop.risk_score ?? 0)), 1),
            generated.risk_data_status,
          )
        : "",
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
        detail: `${stop.departure_minute - stop.arrival_minute} min ${planningAttractions.find((item) => item.id === stop.attraction_id)?.visit_duration_known === false ? "planned (duration unknown; estimate)" : "visit"} · ${stop.travel_minutes_before} min estimated travel${stop.wait_minutes ? ` · ${stop.wait_minutes} min waiting${stop.wait_reason ? ` — ${stop.wait_reason}` : ""}` : ""}`,
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
  const scheduledIds = new Set(
    generated.days.flatMap((day) => day.stops.map((stop) => stop.attraction_id)),
  );
  const scheduledInputs = planningAttractions.filter((item) => scheduledIds.has(item.id));
  const unknownFeeCount = scheduledInputs.filter((item) => item.cost_known === false).length;
  const unknownHoursCount = scheduledInputs.filter(
    (item) => item.opening_window_known === false,
  ).length;
  const estimatedDurationCount = scheduledInputs.filter(
    (item) => item.visit_duration_known === false,
  ).length;
  const detailedWarnings = [
    ...new Set([...generated.warnings, ...generated.days.flatMap((day) => day.warnings)]),
  ];
  const intercityNotice = savedTrips.find((trip) => trip.id === generated.trip_id)?.origin;
  const total = budgetEstimate?.total_estimated ?? generated.total_cost;
  const displayBreakdown = budgetEstimate?.categories.map((item) => ({
    name:
      item.key === "attractions" && unknownFeeCount > 0
        ? `${item.label} amounts (${unknownFeeCount} fee${unknownFeeCount === 1 ? "" : "s"} unknown)`
        : item.label,
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
  const attributions = [
    ...new Set(
      planningAttractions
        .map((item) => item.attribution)
        .filter((value): value is string => Boolean(value)),
    ),
  ];
  const weatherItems = weatherProposal?.weather_summary ?? [];
  const fullWeatherCoverage =
    Boolean(weatherProposal?.forecast_available) &&
    weatherItems.length > 0 &&
    weatherItems.every((item) => item.risk.known && item.risk.confidence === "forecast");
  const weatherFieldLabels: Record<string, string> = {
    precipitation_probability: "rain probability",
    precipitation: "precipitation amount",
    temperature_2m: "temperature",
    apparent_temperature: "feels-like temperature",
    wind_speed_10m: "wind speed",
    weather_code: "weather condition",
  };
  const checkedWeatherConditions = [
    ...new Set(
      weatherItems.flatMap((item) =>
        Object.keys(item.risk.variables).map((field) => weatherFieldLabels[field] ?? field),
      ),
    ),
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
            <Button
              variant="outline"
              disabled={!selectedTripId || downloadingPdf}
              onClick={() => void exportPdf()}
            >
              <Download className="h-4 w-4" /> {downloadingPdf ? "Preparing PDF…" : "Download PDF"}
            </Button>
            <Button
              disabled={!selectedTripId}
              onClick={() => {
                setShareUrl("");
                setShareDialogOpen(true);
              }}
            >
              <Share2 className="h-4 w-4" /> Share
            </Button>
          </>
        }
      />

      {attributions.map((attribution) => (
        <p key={attribution} className="text-xs text-muted-foreground">
          Attraction data attribution: {attribution}
        </p>
      ))}

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
          {generated ? (
            <section className="surface space-y-2 p-3 text-xs" aria-label="Planning assumptions">
              <p className="text-sm text-muted-foreground">
                Some attraction details, risk assessments and transfer times are estimated or
                unavailable. Verify important details before travelling.
              </p>
              <p className="text-muted-foreground">
                Unknown fees: {unknownFeeCount} · Unknown opening hours: {unknownHoursCount} ·
                Estimated visit durations: {estimatedDurationCount} · Risk data:{" "}
                {generated.risk_data_status}
              </p>
              {intercityNotice && (
                <p className="text-muted-foreground">
                  Intercity travel from {intercityNotice} to {generatedDestination} is excluded;
                  this plan covers destination activities only.
                </p>
              )}
              <details>
                <summary className="cursor-pointer font-medium">View planning assumptions</summary>
                <div className="mt-2 space-y-2 text-muted-foreground">
                  <p>
                    Risk data status: {generated.risk_data_status}. Unknown risk remains unavailable
                    and is not treated as a verified zero.
                  </p>
                  <p>
                    Detailed risk inputs and optimizer assumptions are in Advanced Optimization
                    Insights below.
                  </p>
                </div>
              </details>
            </section>
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
                    {day.temp && (
                      <Badge variant="secondary">
                        {day.weather === "Sunny" ? (
                          <Sun className="mr-1 h-3 w-3" />
                        ) : (
                          <CloudSun className="mr-1 h-3 w-3" />
                        )}
                        {day.temp}
                      </Badge>
                    )}
                    {selectedTripId ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={replanning || loadingTripList || loadingSavedTrip}
                        onClick={() => checkWeatherForDay(day.day)}
                      >
                        {replanning ? "Checking…" : "Check weather"}
                      </Button>
                    ) : null}
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
                            disabled={loadingTripList || loadingSavedTrip}
                            onClick={() => void toggleCompleted(slot.attractionId!)}
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

        {weatherUnavailableDay !== null ? (
          <section className="surface border border-border p-4" role="status">
            <p className="font-medium">Weather information unavailable</p>
            <p className="mt-1 text-sm text-muted-foreground">
              We could not retrieve a usable forecast for Day {weatherUnavailableDay}. Your saved
              itinerary is unchanged.
            </p>
          </section>
        ) : null}

        {weatherProposal ? (
          <section className="surface space-y-3 p-5" aria-label="Weather-aware itinerary proposal">
            <div>
              <h2 className="font-semibold">
                Forecast-based proposal · Day {weatherProposal.day_number}
              </h2>
              <p className="text-xs text-muted-foreground">
                {weatherProposal.provider} · forecast updated{" "}
                {formatForecastTimestamp(weatherProposal.retrieved_at)} ·{" "}
                {weatherProposal.attribution}
              </p>
            </div>
            {!weatherProposal.forecast_available ? (
              <p className="text-sm">
                Weather information unavailable. This itinerary has not been assessed for weather
                suitability.
              </p>
            ) : null}
            {weatherProposal.forecast_available ? (
              <div className="space-y-2">
                <div className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
                  {weatherProposal.weather_summary.map((item) => (
                    <WeatherForecastCard key={item.attraction_id} item={item} />
                  ))}
                </div>
                {weatherProposal.weather_summary.some(
                  (item) => !item.risk.known || item.risk.confidence === "partial",
                ) ? (
                  <p className="text-xs text-muted-foreground">
                    Forecast coverage is partial for one or more activities. Unavailable readings
                    are omitted and are not treated as zero.
                  </p>
                ) : null}
              </div>
            ) : null}
            {weatherProposal.changes.length ? (
              <div className="space-y-2">
                {weatherProposal.changes.map((change, index) => (
                  <div
                    key={`${String(change.original["attraction_id"])}-${index}`}
                    className="rounded-md border border-border p-3"
                  >
                    <p className="font-medium">{String(change.original["name"] ?? "Activity")}</p>
                    <p className="text-xs text-muted-foreground">
                      {change.weather_risk?.condition ?? "Forecast condition unavailable"}
                      {change.weather_risk?.forecast_time
                        ? ` · ${formatForecastTimestamp(change.weather_risk.forecast_time)}`
                        : ""}
                    </p>
                    {(change.weather_risk?.advisories ?? []).map((advisory, advisoryIndex) => (
                      <div key={`${advisory.type}-${advisoryIndex}`} className="mt-2 text-sm">
                        <p className="font-medium">{advisoryLabel(advisory.type)}</p>
                        <p className="text-xs text-muted-foreground">{advisory.description}</p>
                      </div>
                    ))}
                    <p className="mt-2 text-xs text-muted-foreground">{change.reason}</p>
                    <p className="mt-1 text-xs font-medium">
                      {change.status === "replaced"
                        ? `Alternative found: ${String(change.revised["name"] ?? "indoor activity")}.`
                        : "No suitable alternative was found; the original activity remains in the plan."}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-md bg-muted/50 p-3">
                {!weatherProposal.forecast_available ? (
                  <p className="text-sm font-medium">Weather information unavailable.</p>
                ) : fullWeatherCoverage ? (
                  <>
                    <p className="text-sm font-medium">
                      {weatherProposal.weather_summary.some(
                        (item) => item.risk.outdoor_suitability_assumed,
                      )
                        ? "Weather conditions look suitable for your scheduled outdoor activities. No changes are currently recommended."
                        : "No weather-driven changes are currently recommended for your scheduled activities."}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Conditions checked:{" "}
                      {checkedWeatherConditions.join(", ") || "available hourly forecast values"}.
                      Forecasts are estimates; conditions can change.
                    </p>
                  </>
                ) : (
                  <>
                    <p className="text-sm font-medium">
                      No changes are currently recommended based on the available forecast values.
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Forecast coverage is partial for one or more activities. Missing values were
                      not treated as zero, so suitability could not be fully assessed.
                    </p>
                  </>
                )}
              </div>
            )}
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-md border border-border p-3">
                <h3 className="text-sm font-medium">Original plan</h3>
                {weatherProposal.original_stops.map((stop) => (
                  <p key={stop.attraction_id} className="mt-1 text-xs text-muted-foreground">
                    {formatClock(stop.arrival_minute)} · {stop.name}
                    {completedAttractionIds.includes(stop.attraction_id) ? " · completed" : ""}
                  </p>
                ))}
              </div>
              <div className="rounded-md border border-border p-3">
                <h3 className="text-sm font-medium">Proposed plan</h3>
                {weatherProposal.revised_stops.map((stop) => (
                  <p key={stop.attraction_id} className="mt-1 text-xs text-muted-foreground">
                    {formatClock(stop.arrival_minute)} · {stop.name}
                    {completedAttractionIds.includes(stop.attraction_id) ? " · completed" : ""}
                  </p>
                ))}
              </div>
            </div>
            {weatherProposal.warnings.map((warning) => (
              <p key={warning} className="text-xs text-muted-foreground">
                {warning}
              </p>
            ))}
            <p className="text-xs text-muted-foreground">
              Estimated change: {weatherProposal.additional_travel_minutes} travel min · ₹
              {weatherProposal.additional_cost.toLocaleString("en-IN")} ·{" "}
              {weatherProposal.within_budget ? "within budget estimate" : "over budget estimate"}
            </p>
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={!weatherProposal.can_accept}
                onClick={() => void acceptProposal()}
              >
                Accept revision
              </Button>
              <Button size="sm" variant="outline" onClick={() => void rejectProposal()}>
                Keep current itinerary
              </Button>
            </div>
          </section>
        ) : null}

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
            <h2 className="font-semibold">
              {budgetEstimate ? "Estimated destination expenses" : "Attraction fees"}
            </h2>
            <p className="text-3xl font-semibold tracking-tight">
              ₹{total.toLocaleString("en-IN")}
            </p>
            {budgetEstimate ? (
              <div className="space-y-1 text-xs text-muted-foreground">
                {!budgetEstimate.is_complete && (
                  <p className="font-medium text-amber-700">
                    Incomplete estimate: {budgetEstimate.unknown_attraction_fee_count} scheduled
                    attraction fee(s) are unknown; the optimizer uses a zero-cost placeholder for
                    those entries.
                  </p>
                )}
                <p>
                  Estimated per person: ₹{budgetEstimate.per_person.toLocaleString("en-IN")} · daily
                  average: ₹{budgetEstimate.daily_average.toLocaleString("en-IN")}
                </p>
                <p>
                  {budgetEstimate.within_budget
                    ? `Listed estimates are ₹${budgetEstimate.remaining_budget.toLocaleString("en-IN")} below your budget`
                    : `Listed estimates are ₹${Math.abs(budgetEstimate.remaining_budget).toLocaleString("en-IN")} over your budget`}
                </p>
                <p>
                  Estimated destination expenses:{" "}
                  {budgetEstimate.budget_limit > 0
                    ? Math.round(
                        (budgetEstimate.total_estimated / budgetEstimate.budget_limit) * 100,
                      )
                    : 0}
                  % of your ₹{budgetEstimate.budget_limit.toLocaleString("en-IN")} budget. Intercity
                  travel and unknown attraction fees are excluded.
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
            {budgetEstimate?.exclusions.length ? (
              <div
                className="space-y-1 rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground"
                role="note"
                aria-label="Budget exclusions"
              >
                <p className="font-medium text-foreground">Excluded costs and estimate limits</p>
                {budgetEstimate.exclusions.map((exclusion) => (
                  <p key={exclusion}>{exclusion}</p>
                ))}
              </div>
            ) : null}
          </div>
          <details className="surface p-4">
            <summary className="cursor-pointer font-semibold">
              Advanced Optimization Insights
            </summary>
            <div className="mt-4 space-y-4">
              <section className="space-y-3 rounded-lg border border-border p-4">
                <div>
                  <h2 className="font-semibold">Optimizer assumptions and technical warnings</h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Risk, relevance, and feasibility signals are limited by the available catalog
                    data; unknown values are not verified zeros.
                  </p>
                </div>
                {generated.days.flatMap((day) => day.stops).length > 0 ? (
                  <ul className="max-h-72 space-y-1 overflow-auto text-xs text-muted-foreground">
                    {generated.days
                      .flatMap((day) => day.stops)
                      .map((stop) => {
                        const place = planningAttractions.find(
                          (item) => item.id === stop.attraction_id,
                        );
                        return (
                          <li key={stop.attraction_id}>
                            {stop.name}:{" "}
                            {riskDetailsLabel(
                              stop.risk_score,
                              stop.risk_data_status,
                              place?.risk_metadata,
                            )}
                            ; planning relevance {Math.round((place?.priority_score ?? 0.5) * 100)}%
                            ({place?.priority_reasons?.join("; ") || "category and interest match"})
                          </li>
                        );
                      })}
                  </ul>
                ) : null}
                {detailedWarnings.length > 0 ? (
                  <ul className="max-h-56 list-inside list-disc space-y-1 overflow-auto text-xs text-muted-foreground">
                    {detailedWarnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                ) : null}
              </section>
              {generated ? (
                <div className="surface space-y-3 p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="font-semibold">Reliability estimate</h2>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Seeded disruption scenarios for the selected stops, using their weather,
                        crowd and availability risk inputs ({generated.data_source}).
                      </p>
                    </div>
                    <Button size="sm" variant="outline" onClick={assessReliability}>
                      Assess
                    </Button>
                  </div>
                  {reliability ? (
                    <div className="text-sm">
                      {reliability.completion_probability === null ||
                      reliability.expected_disruptions === null ? (
                        <p className="font-medium">Risk data unavailable</p>
                      ) : (
                        <>
                          <p className="text-2xl font-semibold">
                            {Math.round(reliability.completion_probability * 100)}%
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            Estimated completion probability ·{" "}
                            {reliability.expected_disruptions.toFixed(2)} expected disruptions (
                            {reliability.risk_data_status})
                          </p>
                        </>
                      )}
                      {reliability.completion_probability === null ? (
                        <p className="mt-1 text-xs text-muted-foreground">
                          Required risk data is incomplete, so no probability was calculated.
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {weatherProposal ? (
                <section
                  className="surface space-y-3 p-5"
                  aria-label="Advanced weather proposal detail"
                >
                  <div>
                    <h2 className="font-semibold">Forecast assessment details</h2>
                    <p className="text-xs text-muted-foreground">
                      {weatherProposal.provider} · {weatherProposal.attribution} · fetched{" "}
                      {new Date(weatherProposal.retrieved_at).toLocaleString()}
                    </p>
                  </div>
                  {!weatherProposal.forecast_available ? (
                    <p className="text-sm">
                      Weather data unavailable for scheduled activities; no risk value was assumed.
                    </p>
                  ) : null}
                  <div className="space-y-2 text-sm">
                    {weatherProposal.changes.map((change, index) => (
                      <div
                        key={`${String(change.original["attraction_id"])}-${index}`}
                        className="rounded-md border border-border p-3"
                      >
                        <p className="font-medium">
                          {change.status}: {String(change.original["name"] ?? "Activity")}
                          {change.status === "replaced"
                            ? ` → ${String(change.revised["name"] ?? "alternative")}`
                            : ""}
                        </p>
                        <p className="text-xs text-muted-foreground">{change.reason}</p>
                      </div>
                    ))}
                  </div>
                  {weatherProposal.warnings.map((warning) => (
                    <p key={warning} className="text-xs text-muted-foreground">
                      {warning}
                    </p>
                  ))}
                  <p className="text-xs text-muted-foreground">
                    Estimated change: {weatherProposal.additional_travel_minutes} travel min · ₹
                    {weatherProposal.additional_cost.toLocaleString("en-IN")} ·{" "}
                    {weatherProposal.within_budget
                      ? "within budget estimate"
                      : "over budget estimate"}
                  </p>
                  <div className="text-xs text-muted-foreground">
                    <p>Forecast assessment coverage</p>
                    <p className="mt-1">
                      {weatherItems.filter((item) => item.risk.known).length} of{" "}
                      {weatherItems.length} activities had enough available data for a weather
                      assessment. Crowd and availability remain separate risk dimensions.
                    </p>
                  </div>
                </section>
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
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => sendFeedback(undefined, true)}
                    >
                      Skip similar
                    </Button>
                  </div>
                </div>
              ) : null}
              {alternatives.length > 0 ? (
                <div className="surface space-y-3 p-5">
                  <div>
                    <h2 className="font-semibold">Single-day optimization alternatives (Pareto)</h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      NSGA-II compares attraction selection trade-offs. Time and risk columns are
                      planning proxies; when source risk data is incomplete, the proxy omits unknown
                      dimensions and is not a safety assessment. A low or zero score is not a safety
                      guarantee. These are comparisons for one day and do not replace this multi-day
                      itinerary.
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
                        <span>
                          {riskProxyLabel(
                            alternative.objectives.risk_proxy,
                            alternative.risk_data_status,
                          )}
                        </span>
                        <span>Utility {alternative.objectives.utility.toFixed(2)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              {annealing ? (
                <div className="surface space-y-2 p-5 text-sm">
                  <h2 className="font-semibold">Single-day simulated annealing comparison</h2>
                  <p className="text-xs text-muted-foreground">
                    This seeded search produces a one-day attraction selection, not a replacement
                    for the full multi-day itinerary. Figures are estimates.
                  </p>
                  <p className="text-muted-foreground">
                    ₹{annealing.total_cost.toLocaleString("en-IN")} ·{" "}
                    {annealing.total_travel_minutes} min · satisfaction{" "}
                    {annealing.satisfaction.toFixed(2)} ·{" "}
                    {riskAssessmentLabel(annealing.risk_score, annealing.risk_data_status)}
                  </p>
                </div>
              ) : null}
              {generated ? (
                <div className="surface space-y-3 p-5">
                  <div>
                    <h2 className="font-semibold">What-if replanning</h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Simulated what-if inputs use synthetic estimates and are not actual forecasts.
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
                        {scenario.total_cost.toLocaleString("en-IN")} ·{" "}
                        {scenario.total_travel_minutes} min
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
            </div>
          </details>
        </aside>
      </div>
      <Dialog open={shareDialogOpen} onOpenChange={setShareDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Share this itinerary</DialogTitle>
            <DialogDescription>
              Anyone with this link can view the itinerary. It does not grant permission to change
              your saved trip.
            </DialogDescription>
          </DialogHeader>
          {shareUrl ? (
            <Input
              aria-label="Read-only share link"
              readOnly
              value={shareUrl}
              onFocus={(event) => event.currentTarget.select()}
            />
          ) : (
            <p className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
              Generate a secure, read-only link. You can revoke it at any time.
            </p>
          )}
          <DialogFooter>
            {shareUrl ? (
              <>
                <Button variant="outline" disabled={shareBusy} onClick={() => void copyShareLink()}>
                  Copy link
                </Button>
                <Button
                  variant="destructive"
                  disabled={shareBusy}
                  onClick={() => void revokeShareLink()}
                >
                  Revoke link
                </Button>
              </>
            ) : (
              <Button
                disabled={shareBusy || !selectedTripId}
                onClick={() => void generateShareLink()}
              >
                {shareBusy ? "Generating…" : "Generate share link"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
