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
import { createAndOptimizeTrip, getAttractionCatalog, getTravelPreferences } from "@/lib/api";
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
    transport: "car",
    intercityTransport: "",
    outboundCost: "",
    returnCost: "",
    hotelBudget: "mid",
    travellers: 2,
    luxury: [3],
    riskTolerance: [0.3],
    walkingTolerance: [0.5],
    crowdTolerance: [0.5],
    pace: [0.5],
    picks: [] as string[],
  });

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
            : preferences.transportation?.toLowerCase() === "motorbike"
              ? "mixed"
              : (preferences.transportation?.toLowerCase() ?? current.transport),
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
      if (
        (outboundCost !== null && (!Number.isFinite(outboundCost) || outboundCost < 0)) ||
        (returnCost !== null && (!Number.isFinite(returnCost) || returnCost < 0))
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
        miscellaneousBudget: 0,
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
                      onChange={(e) => setForm({ ...form, from: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="to">Destination</Label>
                    <Input
                      id="to"
                      value={form.to}
                      onChange={(e) => setForm({ ...form, to: e.target.value })}
                    />
                    {form.from.trim() &&
                      form.to.trim() &&
                      form.from.trim().toLowerCase() !== form.to.trim().toLowerCase() && (
                        <p className="text-xs text-muted-foreground">
                          {form.from.trim()} to {form.to.trim()} intercity travel is not routed or
                          included in this estimate; the itinerary covers activities within{" "}
                          {form.to.trim()}.
                        </p>
                      )}
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
                  <Label>Transportation</Label>
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
                      <SelectItem value="car">Private car</SelectItem>
                      <SelectItem value="train">Train</SelectItem>
                      <SelectItem value="flight">Flights</SelectItem>
                      <SelectItem value="bus">Bus</SelectItem>
                      <SelectItem value="mixed">Mixed</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-3 rounded-xl border border-border p-4">
                  <div>
                    <h3 className="text-sm font-semibold">Intercity transportation</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Optional outbound and return estimates. Entered amounts are your estimates,
                      not quoted fares; leave a leg blank if its cost is unknown.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label>Intercity mode (optional)</Label>
                    <Select
                      value={form.intercityTransport || "unspecified"}
                      onValueChange={(value) =>
                        setForm({
                          ...form,
                          intercityTransport: value === "unspecified" ? "" : value,
                        })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a mode" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="unspecified">Not selected</SelectItem>
                        <SelectItem value="train">Train</SelectItem>
                        <SelectItem value="bus">Bus</SelectItem>
                        <SelectItem value="flight">Flight</SelectItem>
                        <SelectItem value="car">Car</SelectItem>
                        <SelectItem value="mixed">Mixed</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="intercity-outbound-cost">Outbound estimate (INR)</Label>
                      <Input
                        id="intercity-outbound-cost"
                        type="number"
                        min="0"
                        step="1"
                        inputMode="decimal"
                        placeholder="Leave blank if unknown"
                        value={form.outboundCost}
                        onChange={(event) => setForm({ ...form, outboundCost: event.target.value })}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="intercity-return-cost">Return estimate (INR)</Label>
                      <Input
                        id="intercity-return-cost"
                        type="number"
                        min="0"
                        step="1"
                        inputMode="decimal"
                        placeholder="Leave blank if unknown"
                        value={form.returnCost}
                        onChange={(event) => setForm({ ...form, returnCost: event.target.value })}
                      />
                    </div>
                  </div>
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
                    onValueChange={([v]) => setForm({ ...form, travellers: v ?? form.travellers })}
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
