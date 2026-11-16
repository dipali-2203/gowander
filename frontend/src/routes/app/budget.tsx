import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { CalendarDays, Wallet } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/travel/PageHeader";
import { StatCard } from "@/components/travel/StatCard";
import { Button } from "@/components/ui/button";
import { getUserTrips, type AccountTrip } from "@/lib/api";

export const Route = createFileRoute("/app/budget")({
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Budget Dashboard · GoWander" },
      { name: "description", content: "Review the planned budgets for your trips." },
    ],
  }),
  component: Budget,
});

function Budget() {
  const [trips, setTrips] = useState<AccountTrip[]>([]);
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

  const total = trips.reduce((sum, trip) => sum + trip.budget, 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Budget dashboard"
        description="Planned budgets from the trips in your account."
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
          description="Create a trip to see its planned budget here."
          action={
            <Button asChild>
              <Link to="/app/planner">Plan a trip</Link>
            </Button>
          }
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <StatCard
              label="Planned budgets"
              value={total}
              prefix="₹"
              icon={<Wallet className="h-4.5 w-4.5" />}
              hint="Across your trips"
            />
            <StatCard
              label="Trips"
              value={trips.length}
              icon={<CalendarDays className="h-4.5 w-4.5" />}
              hint="In your account"
            />
          </div>
          <section className="surface divide-y divide-border p-5">
            <h2 className="pb-3 font-semibold">Trip budgets</h2>
            {trips.map((trip) => (
              <div key={trip.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                <div>
                  <h3 className="font-medium">{trip.destination}</h3>
                  <p className="text-sm text-muted-foreground">
                    {trip.start_date} – {trip.end_date}
                  </p>
                </div>
                <p className="font-semibold">₹{trip.budget.toLocaleString("en-IN")}</p>
              </div>
            ))}
            <p className="pt-4 text-xs text-muted-foreground">
              This view shows planned trip budgets. The app does not yet track actual expenses.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
