import { useEffect, useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  getTravelPreferences,
  saveTravelPreferences,
  currentUser,
  type UserTravelPreferences,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const interests = [
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
const styles = [
  "Budget Travel",
  "Luxury Travel",
  "Backpacking",
  "Slow Travel",
  "Solo Travel",
  "Family Travel",
  "Group Travel",
  "Couple Travel",
];
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

export function TravelPreferencesSection() {
  const auth = useAuth();
  const [preferences, setPreferences] = useState<UserTravelPreferences>(emptyPreferences);
  const [completed, setCompleted] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getTravelPreferences()
      .then((result) => {
        if (!active) return;
        setPreferences({ ...emptyPreferences, ...result.preferences });
        setCompleted(result.onboarding_completed);
        setSkipped(result.onboarding_skipped);
      })
      .catch((cause) => {
        if (active)
          setError(cause instanceof Error ? cause.message : "Could not load your preferences.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function toggle(key: "interests" | "styles", item: string) {
    setPreferences((current) => ({
      ...current,
      [key]: current[key].includes(item)
        ? current[key].filter((value) => value !== item)
        : [...current[key], item],
    }));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await saveTravelPreferences(preferences);
      const response = await currentUser();
      auth?.setUser(response.user);
      setCompleted(true);
      setSkipped(false);
      toast.success("Travel preferences saved.");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Could not save your preferences.";
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  if (loading)
    return (
      <section className="surface p-6 text-sm text-muted-foreground" role="status">
        Loading your preferences…
      </section>
    );

  return (
    <form onSubmit={save} className="space-y-4">
      {(!completed || skipped) && (
        <section className="surface flex flex-wrap items-center justify-between gap-3 p-5">
          <p className="text-sm text-muted-foreground">
            Your onboarding is incomplete. You can finish it whenever you like.
          </p>
          <Button asChild variant="outline">
            <Link to="/app/onboarding">Continue onboarding</Link>
          </Button>
        </section>
      )}
      <section className="surface space-y-4 p-6">
        <div>
          <h2 className="font-semibold">Travel interests</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Choose the experiences you enjoy. Leave them all clear if you have no preference.
          </p>
        </div>
        <ChoiceList
          options={interests}
          selected={preferences.interests}
          onToggle={(item) => toggle("interests", item)}
        />
      </section>
      <section className="surface space-y-4 p-6">
        <div>
          <h2 className="font-semibold">Travel style</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Select any styles that fit your trips.
          </p>
        </div>
        <ChoiceList
          options={styles}
          selected={preferences.styles}
          onToggle={(item) => toggle("styles", item)}
        />
      </section>
      <section className="surface space-y-4 p-6">
        <h2 className="font-semibold">Budget and pace</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <FieldSelect
            label="Usual budget"
            value={preferences.budget_preference ?? ""}
            values={[
              ["budget", "Budget-conscious"],
              ["moderate", "Moderate"],
              ["premium", "Premium"],
              ["luxury", "Luxury"],
              ["flexible", "Flexible"],
            ]}
            onChange={(value) =>
              setPreferences((current) => ({
                ...current,
                budget_preference: (value || null) as UserTravelPreferences["budget_preference"],
              }))
            }
          />
          <div className="space-y-2">
            <Label htmlFor="daily-budget-edit">Daily budget in INR</Label>
            <Input
              id="daily-budget-edit"
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
              placeholder="Optional"
            />
          </div>
          <FieldSelect
            label="Travel pace"
            value={preferences.travel_pace ?? ""}
            values={[
              ["relaxed", "Relaxed"],
              ["balanced", "Balanced"],
              ["fast", "Fast"],
            ]}
            onChange={(value) =>
              setPreferences((current) => ({
                ...current,
                travel_pace: (value || null) as UserTravelPreferences["travel_pace"],
              }))
            }
          />
          <div className="space-y-2">
            <Label htmlFor="trip-duration-edit">Usual trip duration (days)</Label>
            <Input
              id="trip-duration-edit"
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
          <FieldSelect
            label="Preferred transportation"
            value={preferences.transportation ?? ""}
            values={["Train", "Car", "Bus", "Flight", "Mixed", "Motorbike"].map((item) => [
              item,
              item,
            ])}
            onChange={(value) =>
              setPreferences((current) => ({ ...current, transportation: value || null }))
            }
          />
          <FieldSelect
            label="Accommodation preference"
            value={preferences.accommodation ?? ""}
            values={[
              "Hostel",
              "Budget hotel",
              "Boutique stay",
              "Resort",
              "Homestay",
              "Flexible",
            ].map((item) => [item, item])}
            onChange={(value) =>
              setPreferences((current) => ({ ...current, accommodation: value || null }))
            }
          />
        </div>
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save preferences"}
        </Button>
      </section>
    </form>
  );
}

function ChoiceList({
  options,
  selected,
  onToggle,
}: {
  options: string[];
  selected: string[];
  onToggle: (item: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((item) => (
        <Button
          key={item}
          type="button"
          size="sm"
          variant={selected.includes(item) ? "default" : "outline"}
          aria-pressed={selected.includes(item)}
          onClick={() => onToggle(item)}
        >
          {item}
        </Button>
      ))}
    </div>
  );
}

function FieldSelect({
  label,
  value,
  values,
  onChange,
}: {
  label: string;
  value: string;
  values: string[][];
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
        {values.map(([key, text]) => (
          <option key={key} value={key}>
            {text}
          </option>
        ))}
      </select>
    </div>
  );
}
