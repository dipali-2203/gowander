import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Bookmark, CalendarDays, Copy, MapPin, Pencil, Plus, Trash2 } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/travel/PageHeader";
import { Button } from "@/components/ui/button";
import { deleteTrip, duplicateTrip, getUserTrips, type AccountTrip } from "@/lib/api";
import { toast } from "sonner";

export const Route = createFileRoute("/app/saved")({
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Saved Trips · GoWander" },
      { name: "description", content: "Your planned trips." },
    ],
  }),
  component: Saved,
});

function Saved() {
  const [trips, setTrips] = useState<AccountTrip[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    try {
      setTrips(await getUserTrips());
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load your trips.");
    }
  };

  const duplicate = async (trip: AccountTrip) => {
    try {
      await duplicateTrip(trip.id);
      await reload();
      toast.success("Trip duplicated.");
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not duplicate this trip.");
    }
  };

  const remove = async (trip: AccountTrip) => {
    if (!window.confirm(`Delete “${trip.name}”? This cannot be undone.`)) return;
    try {
      await deleteTrip(trip.id);
      await reload();
      toast.success("Trip deleted.");
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not delete this trip.");
    }
  };

  useEffect(() => {
    let active = true;
    getUserTrips()
      .then((items) => {
        if (active) setTrips(items);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load your trips.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Saved trips"
        description={
          loading
            ? "Loading your trips…"
            : `${trips.length} ${trips.length === 1 ? "trip" : "trips"} in your account`
        }
        actions={
          <Button asChild>
            <Link to="/app/planner">
              <Plus className="h-4 w-4" /> New trip
            </Link>
          </Button>
        }
      />
      {loading ? (
        <div className="surface p-6 text-sm text-muted-foreground" role="status">
          Loading your trips…
        </div>
      ) : error ? (
        <div className="surface p-6 text-sm text-destructive" role="alert">
          {error}
        </div>
      ) : trips.length === 0 ? (
        <EmptyState
          icon={<Bookmark className="h-5 w-5" />}
          title="No trips planned yet."
          description="Your travel adventures will appear here once you start creating itineraries."
          action={
            <Button asChild>
              <Link to="/app/planner">
                <Plus className="mr-2 h-4 w-4" />
                Plan Your First Trip
              </Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {trips.map((trip) => (
            <article key={trip.id} className="surface space-y-4 p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary">
                    <MapPin className="h-5 w-5" />
                  </span>
                  <div className="min-w-0">
                    <h2 className="truncate font-semibold">{trip.name || trip.destination}</h2>
                    <p className="text-xs text-muted-foreground">
                      {trip.origin || "Origin not specified"} → {trip.destination}
                    </p>
                  </div>
                </div>
                <span className="text-sm font-semibold">
                  ₹{trip.budget.toLocaleString("en-IN")}
                </span>
              </div>
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <CalendarDays className="h-4 w-4" />
                {trip.start_date} – {trip.end_date}
              </p>
              <p className="text-sm text-muted-foreground">
                {trip.latest_itinerary ? "Saved itinerary available" : "No itinerary generated yet"}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" asChild>
                  <Link
                    to="/app/trips/$tripId"
                    params={{ tripId: String(trip.id) }}
                    search={{ edit: false }}
                  >
                    Open trip
                  </Link>
                </Button>
                <Button size="sm" variant="outline" asChild>
                  <Link
                    to="/app/trips/$tripId"
                    params={{ tripId: String(trip.id) }}
                    search={{ edit: true }}
                  >
                    <Pencil className="h-4 w-4" /> Edit
                  </Link>
                </Button>
                <Button size="sm" variant="outline" onClick={() => void duplicate(trip)}>
                  <Copy className="h-4 w-4" /> Duplicate
                </Button>
                <Button size="sm" variant="outline" onClick={() => void remove(trip)}>
                  <Trash2 className="h-4 w-4" /> Delete
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
