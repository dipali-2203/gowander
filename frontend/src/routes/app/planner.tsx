import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronLeft, ChevronRight, Loader2, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/travel/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import {
  createAndOptimizeTrip,
  getAttractionCatalog,
  getTravelPreferences,
  getTransportationEstimate,
  type MiscellaneousBudgetMode,
  type TransportationEstimatePreview,
} from "@/lib/api";
import { useTripStore } from "@/store/trip";
import { toast } from "sonner";

export const Route = createFileRoute("/app/planner")({
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Trip Planner · GoWander" },
      {
        name: "description",
        content:
          "Tell the planner your cities, days, budget and interests — the AI builds a day-by-day India itinerary.",
      },
      { property: "og:title", content: "Trip Planner · GoWander" },
      {
        property: "og:description",
        content:
          "A guided multi-step form that turns your preferences into an optimised itinerary.",
      },
    ],
  }),
  component: Planner,
});

const steps = ["Route", "Budget", "Travellers", "Style"] as const;
const interests = [
  "Heritage",
  "Food",
  "Mountains",
  "Beaches",
  "Nature",
  "Adventure",
  "Photography",
  "Spiritual",
  "Nightlife",
  "Shopping",
  "Road Trips",
  "Wellness",
];
const loadingSteps = [
  "Finding destinations…",
  "Optimizing routes…",
  "Searching hotels…",
  "Generating itinerary…",
];

function manualTransportationWarning(
  value: string,
  cost: TransportationEstimatePreview["outbound"] | undefined,
) {
  if (!value.trim()) return null;
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount < 0)
    return "Enter a finite, non-negative whole-group total.";
  if (amount > 5_000_000) return "The maximum manual amount is ₹5,000,000 per leg.";
  if (amount === 0) return "Zero needs explicit confirmation that this leg is genuinely free.";
  if (typeof cost?.range_min === "number" && typeof cost.range_max === "number") {
    const low = cost.range_min;
    const high = cost.range_max;
    if (amount < low * 0.5 || amount > Math.max(high * 2, high + 5000)) {
      return `This is outside the broad indicative range ₹${low.toLocaleString("en-IN")}–₹${high.toLocaleString("en-IN")}. You will need to confirm it is intentional.`;
    }
  }
  return null;
}

function Planner() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [generating, setGenerating] = useState(false);
  const [phase, setPhase] = useState(0);
  const setGenerated = useTripStore((state) => state.setGenerated);
  const editedFields = useRef(new Set<string>());
  const [form, setForm] = useState({
    from: "Delhi",
    to: "Jaipur",
    days: 6,
    budget: [60000],
    transport: "private_car",
    intercityTransport: "",
    outboundCost: "",
    returnCost: "",
    hotelBudget: "mid",
    miscellaneousMode: "automatic" as MiscellaneousBudgetMode,
    miscellaneousAmount: "0",
    travellers: 2,
    luxury: [3],
    riskTolerance: [0.3],
    walkingTolerance: [0.5],
    crowdTolerance: [0.5],
    pace: [0.5],
    picks: [] as string[],
  });
  const [transportEstimate, setTransportEstimate] = useState<TransportationEstimatePreview | null>(
    null,
  );
  const [transportEstimateLoading, setTransportEstimateLoading] = useState(false);
  const [transportEstimateError, setTransportEstimateError] = useState<string | null>(null);

  const refreshTransportEstimate = async (route?: {
    origin?: string;
    destination?: string;
    mode?: string | null;
    travelers?: number;
  }) => {
    const origin = route?.origin ?? form.from.trim();
    const destination = route?.destination ?? form.to.trim();
    if (!origin || !destination || origin.toLowerCase() === destination.toLowerCase()) {
      setTransportEstimate(null);
      return;
    }
    setTransportEstimateLoading(true);
    setTransportEstimateError(null);
    try {
      const estimate = await getTransportationEstimate({
        origin,
        destination,
        travelerCount: route?.travelers ?? form.travellers,
        mode: route?.mode === undefined ? form.intercityTransport || null : route.mode,
        originLatitude: transportEstimate?.origin?.latitude ?? null,
        originLongitude: transportEstimate?.origin?.longitude ?? null,
        destinationLatitude: transportEstimate?.destination?.latitude ?? null,
        destinationLongitude: transportEstimate?.destination?.longitude ?? null,
      });
      setTransportEstimate(estimate);
    } catch (error) {
      setTransportEstimate(null);
      setTransportEstimateError(
        error instanceof Error ? error.message : "Transportation estimate unavailable.",
      );
    } finally {
      setTransportEstimateLoading(false);
    }
  };

  useEffect(() => {
    void refreshTransportEstimate();
    // Initial route estimate only; subsequent route changes are resolved on field blur.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const destination = form.to.trim();
    if (destination) {
      void getAttractionCatalog(destination).catch(() => undefined);
    }
  }, [form.to]);

  useEffect(() => {
    let active = true;
    getTravelPreferences()
      .then(({ preferences }) => {
        if (!active) return;
        const interestAliases: Record<string, string> = {
          "Heritage and History": "Heritage",
          "Food and Culinary Experiences": "Food",
          "Mountains and Trekking": "Mountains",
          "Nature and Wildlife": "Nature",
          "Spiritual and Cultural Travel": "Spiritual",
          "Relaxation and Wellness": "Wellness",
          "Road Trips": "Road Trips",
        };
        const selected = preferences.interests
          .map((interest) => interestAliases[interest] ?? interest)
          .filter((interest) => interests.includes(interest));
        const accommodationDefaults: Record<string, string> = {
          hostel: "low",
          "budget hotel": "low",
        };
        setForm((current) => ({
          ...current,
          picks: editedFields.current.has("picks") ? current.picks : selected,
          days: editedFields.current.has("days")
            ? current.days
            : (preferences.preferred_trip_duration_days ?? current.days),
          budget:
            editedFields.current.has("budget") ||
            typeof preferences.daily_budget_inr !== "number" ||
            preferences.daily_budget_inr <= 0
              ? current.budget
              : [
                  preferences.daily_budget_inr *
                    (editedFields.current.has("days")
                      ? current.days
                      : (preferences.preferred_trip_duration_days ?? current.days)),
                ],
          transport: editedFields.current.has("transport")
            ? current.transport
            : ({
                car: "private_car",
                "private car": "private_car",
                "public transport": "public_transport",
                transit: "public_transport",
                metro: "public_transport",
                bus: "public_transport",
                train: "public_transport",
                walking: "walking",
                walk: "walking",
                "rental vehicle": "rental_vehicle",
                rental_vehicle: "rental_vehicle",
                auto: "auto",
                "auto/taxi": "auto",
                taxi: "auto",
                cab: "auto",
                motorbike: "auto",
              }[preferences.transportation?.toLowerCase() ?? ""] ?? current.transport),
          pace: editedFields.current.has("pace")
            ? current.pace
            : preferences.travel_pace === "relaxed"
              ? [0.25]
              : preferences.travel_pace === "fast"
                ? [0.8]
                : preferences.travel_pace === null &&
                    preferences.styles.some((style) => style.toLowerCase() === "slow travel")
                  ? [0.25]
                  : current.pace,
          hotelBudget: editedFields.current.has("hotelBudget")
            ? current.hotelBudget
            : (accommodationDefaults[preferences.accommodation?.trim().toLowerCase() ?? ""] ??
              current.hotelBudget),
        }));
      })
      .catch(() => {
        // The trip planner remains usable when profile preferences are unavailable.
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!generating) return;
    if (phase >= loadingSteps.length) {
      const t = setTimeout(
        () => navigate({ to: "/app/itinerary", search: { tripId: undefined } }),
        500,
      );
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setPhase((p) => p + 1), 1100);
    return () => clearTimeout(t);
  }, [generating, phase, navigate]);

  const toggleInterest = (i: string) => {
    editedFields.current.add("picks");
    setForm((f) => ({
      ...f,
      picks: f.picks.includes(i) ? f.picks.filter((p) => p !== i) : [...f.picks, i],
    }));
  };

  const generateItinerary = async () => {
    try {
      const destination = form.to.trim();
      const outboundCost = form.outboundCost.trim() ? Number(form.outboundCost) : null;
      const returnCost = form.returnCost.trim() ? Number(form.returnCost) : null;
      const miscellaneousAmount = form.miscellaneousAmount.trim()
        ? Number(form.miscellaneousAmount)
        : 0;
      if (
        form.miscellaneousMode === "manual" &&
        (!Number.isFinite(miscellaneousAmount) ||
          miscellaneousAmount < 0 ||
          miscellaneousAmount > 5_000_000)
      ) {
        throw new Error("Enter a non-negative miscellaneous amount up to ₹5,000,000.");
      }
      if (
        (outboundCost !== null &&
          (!Number.isFinite(outboundCost) || outboundCost < 0 || outboundCost > 5_000_000)) ||
        (returnCost !== null &&
          (!Number.isFinite(returnCost) || returnCost < 0 || returnCost > 5_000_000))
      ) {
        throw new Error("Enter a valid non-negative cost for each known intercity leg.");
      }
      const result = await createAndOptimizeTrip({
        origin: form.from.trim(),
        destination,
        days: form.days,
        budget: form.budget[0] ?? 0,
        travelerCount: form.travellers,
        accommodationCategory:
          form.hotelBudget === "low"
            ? "budget"
            : form.hotelBudget === "high"
              ? "premium"
              : form.hotelBudget === "lux"
                ? "luxury"
                : "standard",
        luxuryLevel: form.luxury[0] ?? 3,
        miscellaneousBudget: form.miscellaneousMode === "manual" ? miscellaneousAmount : 0,
        miscellaneousBudgetMode: form.miscellaneousMode,
        intercityTransportationMode: form.intercityTransport || null,
        intercityOutboundCost: outboundCost,
        intercityReturnCost: returnCost,
        mealPreferences: [],
        interests: form.picks,
        preferences: {
          riskTolerance: form.riskTolerance[0] ?? 0.3,
          walkingTolerance: form.walkingTolerance[0] ?? 0.5,
          crowdTolerance: form.crowdTolerance[0] ?? 0.5,
          pace: form.pace[0] ?? 0.5,
          transport: form.transport,
        },
      });
      setGenerated(
        result.itinerary,
        destination,
        result.alternatives,
        result.attractions,
        result.startLocation,
        result.budget,
        result.annealing,
      );
      setPhase(0);
      setGenerating(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not generate this itinerary.");
    }
  };

  if (generating) {
    return (
      <div className="grid min-h-[70dvh] place-items-center">
        <div className="surface w-full max-w-md space-y-6 p-8 text-center">
          <motion.span
            animate={{ rotate: 360 }}
            transition={{ repeat: Infinity, duration: 2.4, ease: "linear" }}
            className="gradient-primary mx-auto grid h-14 w-14 place-items-center rounded-2xl text-primary-foreground"
          >
            <Sparkles className="h-6 w-6" />
          </motion.span>
          <div>
            <h2 className="text-lg font-semibold">Building your trip</h2>
            <p className="text-sm text-muted-foreground">
              {form.days} days · {form.from} → {form.to}
            </p>
          </div>
          <ul className="space-y-3 text-left">
            {loadingSteps.map((s, i) => (
              <li key={s} className="flex items-center gap-3 text-sm">
                {i < phase ? (
                  <Check className="h-4 w-4 shrink-0 text-success" />
                ) : i === phase ? (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
                ) : (
                  <span className="h-4 w-4 shrink-0 rounded-full border border-border" />
                )}
                <span className={i <= phase ? "" : "text-muted-foreground"}>{s}</span>
              </li>
            ))}
          </ul>
          <Progress value={(phase / loadingSteps.length) * 100} className="h-2" />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        title="Plan a new trip"
        description="Four short steps. Everything stays editable after generation."
      />

      <ol className="grid grid-cols-4 gap-2" aria-label="Progress">
        {steps.map((s, i) => (
          <li key={s} className="space-y-2">
            <div
              className={cn(
                "h-1.5 rounded-full transition-colors",
                i <= step ? "bg-primary" : "bg-border",
              )}
            />
            <span
              className={cn(
                "truncate text-xs font-medium",
                i <= step ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {s}
            </span>
          </li>
        ))}
      </ol>

      <div className="surface p-6">
        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -24 }}
            transition={{ duration: 0.25 }}
            className="space-y-5"
          >
            {step === 0 && (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="from">Starting city</Label>
                    <Input
                      id="from"
                      value={form.from}
                      onChange={(e) => {
                        setTransportEstimate(null);
                        setForm({ ...form, from: e.target.value });
                      }}
                      onBlur={() => void refreshTransportEstimate()}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="to">Destination</Label>
                    <Input
                      id="to"
                      value={form.to}
                      onChange={(e) => {
                        setTransportEstimate(null);
                        setForm({ ...form, to: e.target.value });
                      }}
                      onBlur={() => void refreshTransportEstimate()}
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="days">Travel days — {form.days}</Label>
                  <Slider
                    id="days"
                    min={1}
                    max={21}
                    step={1}
                    value={[form.days]}
                    onValueChange={([v]) => {
                      editedFields.current.add("days");
                      setForm({ ...form, days: v ?? form.days });
                    }}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Local transportation</Label>
                  <Select
                    value={form.transport}
                    onValueChange={(v) => {
                      editedFields.current.add("transport");
                      setForm({ ...form, transport: v });
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="private_car">Private car</SelectItem>
                      <SelectItem value="walking">Walking</SelectItem>
                      <SelectItem value="public_transport">Public transport</SelectItem>
                      <SelectItem value="auto">Auto / Taxi</SelectItem>
                      <SelectItem value="rental_vehicle">Rental vehicle</SelectItem>
                      <SelectItem value="mixed">Mixed</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Covers movement within the destination city only.
                  </p>
                </div>
                <div className="space-y-3 rounded-xl border border-border p-4">
                  <div>
                    <h3 className="text-sm font-semibold">Intercity transportation</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Whole-group travel costs between these cities. Estimates are assumptions, not
                      live fares. Blur a city field to refresh.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label>Intercity mode (optional)</Label>
                    <Select
                      value={form.intercityTransport || "unspecified"}
                      onValueChange={(value) => {
                        const mode = value === "unspecified" ? null : value;
                        setForm({
                          ...form,
                          intercityTransport: mode ?? "",
                        });
                        void refreshTransportEstimate({ mode });
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a mode" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="unspecified">Not decided · provisional range</SelectItem>
                        <SelectItem value="train">Train</SelectItem>
                        <SelectItem value="bus">Bus</SelectItem>
                        <SelectItem value="flight">Flight</SelectItem>
                        <SelectItem value="private_car">Private car</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="intercity-outbound-cost">
                        Outbound cost · whole group (INR)
                      </Label>
                      <Input
                        id="intercity-outbound-cost"
                        type="number"
                        min="0"
                        max="5000000"
                        step="1"
                        inputMode="decimal"
                        placeholder="Optional manual override"
                        value={form.outboundCost}
                        onChange={(event) => setForm({ ...form, outboundCost: event.target.value })}
                      />
                      {manualTransportationWarning(
                        form.outboundCost,
                        transportEstimate?.outbound,
                      ) && (
                        <p className="text-xs text-amber-700 dark:text-amber-300" role="status">
                          {manualTransportationWarning(
                            form.outboundCost,
                            transportEstimate?.outbound,
                          )}
                        </p>
                      )}
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="intercity-return-cost">Return cost · whole group (INR)</Label>
                      <Input
                        id="intercity-return-cost"
                        type="number"
                        min="0"
                        max="5000000"
                        step="1"
                        inputMode="decimal"
                        placeholder="Optional manual override"
                        value={form.returnCost}
                        onChange={(event) => setForm({ ...form, returnCost: event.target.value })}
                      />
                      {manualTransportationWarning(form.returnCost, transportEstimate?.return) && (
                        <p className="text-xs text-amber-700 dark:text-amber-300" role="status">
                          {manualTransportationWarning(form.returnCost, transportEstimate?.return)}
                        </p>
                      )}
                    </div>
                  </div>
                  {transportEstimateLoading && (
                    <p className="text-xs text-muted-foreground">Estimating route costs…</p>
                  )}
                  {transportEstimateError && (
                    <p role="status" className="text-xs text-amber-700 dark:text-amber-300">
                      {transportEstimateError}
                    </p>
                  )}
                  {transportEstimate && (
                    <div
                      className="grid gap-2 rounded-lg bg-muted/50 p-3 text-sm sm:grid-cols-2"
                      aria-label="Indicative intercity estimates"
                    >
                      {transportEstimate.origin?.display_name &&
                        transportEstimate.destination?.display_name && (
                          <p className="text-xs text-muted-foreground sm:col-span-2">
                            Route resolved as {transportEstimate.origin.display_name} →{" "}
                            {transportEstimate.destination.display_name}
                          </p>
                        )}
                      {(["outbound", "return"] as const).map((direction) => {
                        const cost = transportEstimate[direction];
                        return (
                          <div key={direction}>
                            <p className="text-xs font-medium capitalize text-muted-foreground">
                              {direction} · {cost.mode ?? "mode not decided"}
                            </p>
                            {cost.mode_estimates && cost.status === "unavailable" ? (
                              <div className="mt-2 space-y-2">
                                <p className="font-medium">Choose a mode to use an estimate</p>
                                {Object.entries(cost.mode_estimates).map(([mode, option]) => (
                                  <div
                                    className="rounded-md border bg-background/70 p-2"
                                    key={mode}
                                  >
                                    <p className="text-xs font-medium capitalize">
                                      {mode.replaceAll("_", " ")}
                                    </p>
                                    {typeof option.range_min === "number" &&
                                    typeof option.range_max === "number" ? (
                                      <p className="text-xs text-muted-foreground">
                                        Indicative {option.range_min.toLocaleString("en-IN")}–
                                        {option.range_max.toLocaleString("en-IN")} INR · whole group
                                      </p>
                                    ) : (
                                      <p className="text-xs text-muted-foreground">
                                        Estimate unavailable
                                      </p>
                                    )}
                                    <p className="text-xs text-muted-foreground">
                                      {option.unit_basis?.replaceAll("_", " ")} pricing
                                    </p>
                                  </div>
                                ))}
                              </div>
                            ) : cost.status === "estimated" && typeof cost.amount === "number" ? (
                              <p className="font-semibold">
                                ₹{cost.amount.toLocaleString("en-IN")} representative
                              </p>
                            ) : (
                              <p className="font-medium">Estimate unavailable</p>
                            )}
                            {typeof cost.range_min === "number" &&
                              typeof cost.range_max === "number" && (
                                <p className="text-xs text-muted-foreground">
                                  Indicative range ₹{cost.range_min.toLocaleString("en-IN")}–₹
                                  {cost.range_max.toLocaleString("en-IN")} · whole group
                                </p>
                              )}
                            {cost.unit_basis && (
                              <p className="text-xs text-muted-foreground">
                                Rate basis: {cost.unit_basis.replaceAll("_", " ")} · amount is for
                                the whole group ({cost.traveler_count ?? form.travellers}{" "}
                                traveler(s))
                              </p>
                            )}
                            {cost.assumptions.slice(0, 2).map((assumption) => (
                              <p className="mt-1 text-xs text-muted-foreground" key={assumption}>
                                {assumption}
                              </p>
                            ))}
                            <p className="mt-1 text-xs text-muted-foreground">
                              {form[direction === "outbound" ? "outboundCost" : "returnCost"].trim()
                                ? "Your manual amount takes priority."
                                : "Optional: enter your whole-group cost to override."}
                            </p>
                          </div>
                        );
                      })}
                      <p className="text-xs text-muted-foreground sm:col-span-2">
                        {transportEstimate.distance_basis === "osrm_road_route"
                          ? "Private-car range uses an OSRM road route; train distance remains a straight-line proxy."
                          : "Train distance uses a straight-line proxy; bus and private-car ranges use straight-line-derived road-distance proxies."}
                        {transportEstimate.attribution
                          ? ` Geocoding: ${transportEstimate.attribution}.`
                          : ""}
                      </p>
                    </div>
                  )}
                </div>
              </>
            )}

            {step === 1 && (
              <>
                <div className="space-y-2">
                  <Label>Total budget — ₹{(form.budget[0] ?? 0).toLocaleString("en-IN")}</Label>
                  <Slider
                    min={10000}
                    max={300000}
                    step={5000}
                    value={form.budget}
                    onValueChange={(v) => {
                      editedFields.current.add("budget");
                      setForm({ ...form, budget: v });
                    }}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Hotel budget per night</Label>
                  <Select
                    value={form.hotelBudget}
                    onValueChange={(v) => {
                      editedFields.current.add("hotelBudget");
                      setForm({ ...form, hotelBudget: v });
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">Under ₹2,000</SelectItem>
                      <SelectItem value="mid">₹2,000 – ₹6,000</SelectItem>
                      <SelectItem value="high">₹6,000 – ₹15,000</SelectItem>
                      <SelectItem value="lux">₹15,000+</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-3 rounded-xl border border-border p-4">
                  <div>
                    <Label htmlFor="miscellaneous-mode">Miscellaneous allowance</Label>
                    <p className="mt-1 text-xs text-muted-foreground">
                      A whole-trip allowance for incidental expenses.
                    </p>
                  </div>
                  <Select
                    value={form.miscellaneousMode}
                    onValueChange={(value) =>
                      setForm({
                        ...form,
                        miscellaneousMode: value as MiscellaneousBudgetMode,
                      })
                    }
                  >
                    <SelectTrigger id="miscellaneous-mode">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="automatic">Automatic estimate</SelectItem>
                      <SelectItem value="manual">Manual amount</SelectItem>
                      <SelectItem value="disabled">No allowance</SelectItem>
                    </SelectContent>
                  </Select>
                  {form.miscellaneousMode === "automatic" ? (
                    <p className="text-xs text-muted-foreground" role="status">
                      The representative estimate is 10% of the other six budget categories, with an
                      indicative 5–15% range. It may be provisional when those categories have
                      unavailable or partial costs. The planner calculates it after the itinerary is
                      generated.
                    </p>
                  ) : form.miscellaneousMode === "manual" ? (
                    <>
                      <div className="space-y-2">
                        <Label htmlFor="miscellaneous-amount">Manual whole-trip amount (INR)</Label>
                        <Input
                          id="miscellaneous-amount"
                          type="number"
                          min="0"
                          max="5000000"
                          step="1"
                          inputMode="decimal"
                          value={form.miscellaneousAmount}
                          onChange={(event) =>
                            setForm({ ...form, miscellaneousAmount: event.target.value })
                          }
                        />
                      </div>
                      <p className="text-xs text-muted-foreground">
                        This amount, including an explicit ₹0, overrides the automatic estimate.
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Miscellaneous expenses are excluded from the estimate.
                    </p>
                  )}
                </div>
              </>
            )}

            {step === 2 && (
              <>
                <div className="space-y-2">
                  <Label htmlFor="travellers">Travellers — {form.travellers}</Label>
                  <Slider
                    id="travellers"
                    min={1}
                    max={12}
                    step={1}
                    value={[form.travellers]}
                    onValueChange={([v]) => {
                      const travelers = v ?? form.travellers;
                      setForm({ ...form, travellers: travelers });
                      if (transportEstimate) void refreshTransportEstimate({ travelers });
                    }}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Travel interests</Label>
                  <div className="flex flex-wrap gap-2">
                    {interests.map((i) => {
                      const on = form.picks.includes(i);
                      return (
                        <button
                          key={i}
                          type="button"
                          aria-pressed={on}
                          onClick={() => toggleInterest(i)}
                          className={cn(
                            "rounded-full border px-3.5 py-1.5 text-sm transition-colors",
                            on
                              ? "border-primary bg-primary-soft text-primary"
                              : "border-border hover:bg-muted",
                          )}
                        >
                          {i}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </>
            )}

            {step === 3 && (
              <>
                <div className="space-y-2">
                  <Label>Luxury level — {form.luxury[0] ?? 3} / 5</Label>
                  <Slider
                    min={1}
                    max={5}
                    step={1}
                    value={form.luxury}
                    onValueChange={(v) => setForm({ ...form, luxury: v })}
                  />
                  <p className="text-xs text-muted-foreground">
                    1 = hostels and local transport · 5 = heritage suites and private cars
                  </p>
                </div>
                <div className="grid gap-5 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label>
                      Risk tolerance — {Math.round((form.riskTolerance[0] ?? 0) * 100)}%
                    </Label>
                    <Slider
                      min={0}
                      max={1}
                      step={0.1}
                      value={form.riskTolerance}
                      onValueChange={(v) => setForm({ ...form, riskTolerance: v })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>
                      Walking tolerance — {Math.round((form.walkingTolerance[0] ?? 0) * 100)}%
                    </Label>
                    <Slider
                      min={0}
                      max={1}
                      step={0.1}
                      value={form.walkingTolerance}
                      onValueChange={(v) => setForm({ ...form, walkingTolerance: v })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>
                      Crowd tolerance — {Math.round((form.crowdTolerance[0] ?? 0) * 100)}%
                    </Label>
                    <Slider
                      min={0}
                      max={1}
                      step={0.1}
                      value={form.crowdTolerance}
                      onValueChange={(v) => setForm({ ...form, crowdTolerance: v })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Travel pace — {Math.round((form.pace[0] ?? 0) * 100)}%</Label>
                    <Slider
                      min={0}
                      max={1}
                      step={0.1}
                      value={form.pace}
                      onValueChange={(v) => {
                        editedFields.current.add("pace");
                        setForm({ ...form, pace: v });
                      }}
                    />
                  </div>
                </div>
                <div className="rounded-xl bg-muted/60 p-4 text-sm">
                  <p className="font-medium">Summary</p>
                  <p className="mt-1 text-muted-foreground">
                    {form.days} days from {form.from} to {form.to} for {form.travellers} travellers,
                    around ₹{(form.budget[0] ?? 0).toLocaleString("en-IN")}.
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {form.picks.map((p) => (
                      <Badge key={p} variant="secondary">
                        {p}
                      </Badge>
                    ))}
                  </div>
                </div>
              </>
            )}
          </motion.div>
        </AnimatePresence>

        <div className="mt-8 flex items-center justify-between">
          <Button
            variant="ghost"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
          >
            <ChevronLeft className="h-4 w-4" /> Back
          </Button>
          {step < steps.length - 1 ? (
            <Button onClick={() => setStep((s) => s + 1)}>
              Continue <ChevronRight className="h-4 w-4" />
            </Button>
          ) : (
            <Button onClick={generateItinerary}>
              <Sparkles className="h-4 w-4" /> Generate itinerary
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
