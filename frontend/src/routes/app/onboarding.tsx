import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  completeOnboarding,
  currentUser,
  getTravelPreferences,
  skipOnboarding,
  type AuthUser,
  type UserTravelPreferences,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/app/onboarding")({ component: Onboarding });

const interestOptions = [
  "Heritage and History",
  "Food and Culinary Experiences",
  "Mountains and Trekking",
  "Beaches",
  "Adventure",
  "Nature and Wildlife",
  "Photography",
  "Shopping",
  "Spiritual and Cultural Travel",
  "Relaxation and Wellness",
  "Nightlife",
  "Road Trips",
];
const styleOptions = [
  "Budget Travel",
  "Luxury Travel",
  "Backpacking",
  "Slow Travel",
  "Solo Travel",
  "Family Travel",
  "Group Travel",
  "Couple Travel",
];
const steps = ["Welcome", "Interests", "Travel style", "Budget", "Travel preferences"];
const emptyPreferences: UserTravelPreferences = {
  interests: [],
  styles: [],
  budget_preference: null,
  daily_budget_inr: null,
  transportation: null,
  accommodation: null,
  preferred_trip_duration_days: null,
  travel_pace: null,
};

function Onboarding() {
  const navigate = useNavigate();
  const auth = useAuth();
  const setAuthUser = auth?.setUser;
  const [user, setUser] = useState<AuthUser | null>(auth?.user ?? null);
  const [preferences, setPreferences] = useState<UserTravelPreferences>(
    auth?.user.travel_preferences ?? emptyPreferences,
  );
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([currentUser(), getTravelPreferences()])
      .then(([current, saved]) => {
        if (!active) return;
        setUser(current.user);
        setPreferences({ ...emptyPreferences, ...saved.preferences });
        setAuthUser?.(current.user);
      })
      .catch((cause) =>
        toast.error(cause instanceof Error ? cause.message : "Could not load onboarding."),
      )
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [setAuthUser]);

  function toggle(key: "interests" | "styles", value: string) {
    setPreferences((current) => {
      const values = current[key];
      return {
        ...current,
        [key]: values.includes(value)
          ? values.filter((item) => item !== value)
          : [...values, value],
      };
    });
  }

  async function finish(skip: boolean) {
    setSaving(true);
    try {
      if (skip) {
        await skipOnboarding(preferences);
        const response = await currentUser();
        setAuthUser?.(response.user);
        toast("You can finish setting up your travel preferences any time in Settings.");
      } else {
        const response = await completeOnboarding(preferences);
        setUser(response.user);
        setAuthUser?.(response.user);
        toast.success(`You're all set, ${response.user.first_name}!`);
      }
      await navigate({ to: "/app/dashboard", replace: true });
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not save your preferences.");
    } finally {
      setSaving(false);
    }
  }

  if (loading)
    return (
      <div className="surface p-8 text-sm text-muted-foreground" role="status">
        Preparing your travel profile…
      </div>
    );

  return (
    <main className="mx-auto grid min-h-[75dvh] max-w-3xl place-items-center">
      <section className="surface w-full space-y-7 p-6 sm:p-9">
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm font-medium text-primary">Personalize your GoWander experience</p>
          <Button variant="ghost" size="sm" onClick={() => void finish(true)} disabled={saving}>
            Skip for now
          </Button>
        </div>
        <Progress value={((step + 1) / steps.length) * 100} className="h-2" />

        {step === 0 && (
          <div className="space-y-4 py-6 text-center">
            <span className="gradient-primary mx-auto grid h-14 w-14 place-items-center rounded-2xl text-primary-foreground">
              <Sparkles className="h-6 w-6" />
            </span>
            <h1 className="text-3xl font-semibold tracking-tight">
              Welcome to GoWander{user?.first_name ? `, ${user.first_name}` : ""}!
            </h1>
            <p className="text-muted-foreground">
              Let&apos;s personalize your travel experience. Choose what matters to you; you can
              change everything later.
            </p>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <div>
              <h1 className="text-2xl font-semibold">What do you enjoy exploring?</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Choose any interests that sound like you. This is optional.
              </p>
            </div>
            <ChoiceGrid
              options={interestOptions}
              selected={preferences.interests}
              onToggle={(value) => toggle("interests", value)}
            />
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div>
              <h1 className="text-2xl font-semibold">How do you like to travel?</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Select any travel styles that fit.
              </p>
            </div>
            <ChoiceGrid
              options={styleOptions}
              selected={preferences.styles}
              onToggle={(value) => toggle("styles", value)}
            />
          </div>
        )}

        {step === 3 && (
          <div className="space-y-5">
            <div>
              <h1 className="text-2xl font-semibold">What&apos;s your usual budget?</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                This helps us tailor suggestions. You can leave it flexible.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  ["budget", "Budget-conscious"],
                  ["moderate", "Moderate"],
                  ["premium", "Premium"],
                  ["luxury", "Luxury"],
                  ["flexible", "Flexible / no fixed budget"],
                ] as const
              ).map(([value, label]) => (
                <Button
                  key={value}
                  type="button"
                  variant={preferences.budget_preference === value ? "default" : "outline"}
                  className="justify-start"
                  onClick={() =>
                    setPreferences((current) => ({ ...current, budget_preference: value }))
                  }
                >
                  {preferences.budget_preference === value && <Check className="mr-2 h-4 w-4" />}
                  {label}
                </Button>
              ))}
            </div>
            <div className="max-w-xs space-y-2">
              <Label htmlFor="daily-budget">Approximate daily budget in INR (optional)</Label>
              <Input
                id="daily-budget"
                type="number"
                min={0}
                max={5000000}
                value={preferences.daily_budget_inr ?? ""}
                onChange={(event) =>
                  setPreferences((current) => ({
                    ...current,
                    daily_budget_inr: event.target.value ? Number(event.target.value) : null,
                  }))
                }
                placeholder="e.g. 5000"
              />
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-5">
            <div>
              <h1 className="text-2xl font-semibold">A few optional details</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Skip anything you don&apos;t want to answer.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <PreferenceSelect
                label="Preferred transportation"
                value={preferences.transportation ?? ""}
                values={["Train", "Car", "Bus", "Flight", "Mixed", "Motorbike"]}
                onChange={(value) =>
                  setPreferences((current) => ({ ...current, transportation: value || null }))
                }
              />
              <PreferenceSelect
                label="Accommodation style"
                value={preferences.accommodation ?? ""}
                values={[
                  "Hostel",
                  "Budget hotel",
                  "Boutique stay",
                  "Resort",
                  "Homestay",
                  "Flexible",
                ]}
                onChange={(value) =>
                  setPreferences((current) => ({ ...current, accommodation: value || null }))
                }
              />
              <div className="space-y-2">
                <Label htmlFor="duration">Usual trip length (days)</Label>
                <Input
                  id="duration"
                  type="number"
                  min={1}
                  max={60}
                  value={preferences.preferred_trip_duration_days ?? ""}
                  onChange={(event) =>
                    setPreferences((current) => ({
                      ...current,
                      preferred_trip_duration_days: event.target.value
                        ? Number(event.target.value)
                        : null,
                    }))
                  }
                  placeholder="Optional"
                />
              </div>
              <PreferenceSelect
                label="Travel pace"
                value={preferences.travel_pace ?? ""}
                values={["Relaxed", "Balanced", "Fast"]}
                onChange={(value) =>
                  setPreferences((current) => ({
                    ...current,
                    travel_pace: value
                      ? (value.toLowerCase() as UserTravelPreferences["travel_pace"])
                      : null,
                  }))
                }
              />
            </div>
          </div>
        )}

        <footer className="flex items-center justify-between border-t border-border pt-5">
          <Button
            variant="outline"
            onClick={() => setStep((current) => Math.max(0, current - 1))}
            disabled={step === 0 || saving}
          >
            <ChevronLeft className="mr-1 h-4 w-4" /> Back
          </Button>
          <span className="text-xs text-muted-foreground">
            {steps[step]} · {step + 1} of {steps.length}
          </span>
          {step < steps.length - 1 ? (
            <Button
              onClick={() => setStep((current) => Math.min(steps.length - 1, current + 1))}
              disabled={saving}
            >
              Continue <ChevronRight className="ml-1 h-4 w-4" />
            </Button>
          ) : (
            <Button onClick={() => void finish(false)} disabled={saving}>
              {saving ? "Saving…" : "Finish setup"}
            </Button>
          )}
        </footer>
      </section>
    </main>
  );
}

function ChoiceGrid({
  options,
  selected,
  onToggle,
}: {
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {options.map((option) => (
        <Button
          key={option}
          type="button"
          variant={selected.includes(option) ? "default" : "outline"}
          className="justify-start"
          aria-pressed={selected.includes(option)}
          onClick={() => onToggle(option)}
        >
          {selected.includes(option) && <Check className="mr-2 h-4 w-4" />}
          {option}
        </Button>
      ))}
    </div>
  );
}

function PreferenceSelect({
  label,
  value,
  values,
  onChange,
}: {
  label: string;
  value: string;
  values: string[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <select
        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">No preference</option>
        {values.map((item) => (
          <option key={item} value={item}>
            {item}
          </option>
        ))}
      </select>
    </div>
  );
}
