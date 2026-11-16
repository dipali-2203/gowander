import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Bookmark, Compass, MapPinned, Plane, Settings, Sparkles } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/travel/PageHeader";
import { StatCard } from "@/components/travel/StatCard";
import { Button } from "@/components/ui/button";
import { getBookmarks, getUserTrips, type AccountTrip } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/app/dashboard")({
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Dashboard · GoWander" },
      { name: "description", content: "Your trips, preferences and saved destinations." },
    ],
  }),
  component: Dashboard,
});

function Dashboard() {
  const auth = useAuth();
  const [trips, setTrips] = useState<AccountTrip[]>([]);
  const [bookmarkCount, setBookmarkCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([getUserTrips(), getBookmarks()])
      .then(([userTrips, bookmarks]) => {
        if (!active) return;
        setTrips(userTrips);
        setBookmarkCount(bookmarks.items.length);
      })
      .catch((cause) => {
        if (active)
          setError(cause instanceof Error ? cause.message : "Could not load your travel details.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const preferences = auth?.user.travel_preferences;
  const firstName = auth?.user.first_name || auth?.user.name.split(/\s+/)[0] || "traveler";
  const plannedBudget = trips.reduce((total, trip) => total + trip.budget, 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Welcome back, ${firstName}`}
        description="Your travel plans and saved places, all in one place."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/app/explore">
                <Compass className="h-4 w-4" />
                Explore destinations
              </Link>
            </Button>
            <Button asChild>
              <Link to="/app/planner">
                <Sparkles className="h-4 w-4" />
                Plan a trip
              </Link>
            </Button>
          </>
        }
      />

      {error && (
        <p className="surface p-4 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Your trips"
          value={trips.length}
          icon={<Plane className="h-4.5 w-4.5" />}
          hint={loading ? "Loading" : "Trips planned by you"}
        />
        <StatCard
          label="Planned budget"
          value={plannedBudget}
          prefix="₹"
          icon={<MapPinned className="h-4.5 w-4.5" />}
          hint="Across your trips"
        />
        <StatCard
          label="Saved destinations"
          value={bookmarkCount}
          icon={<Bookmark className="h-4.5 w-4.5" />}
          hint="Your bookmarks"
        />
        <StatCard
          label="Travel interests"
          value={preferences?.interests.length ?? 0}
          icon={<Sparkles className="h-4.5 w-4.5" />}
          hint="In your preferences"
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,1fr)]">
        <section className="surface space-y-4 p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold">Your trips</h2>
            <Link to="/app/saved" className="text-sm font-medium text-primary hover:underline">
              View all
            </Link>
          </div>
          {loading ? (
            <p className="text-sm text-muted-foreground" role="status">
              Loading your trips…
            </p>
          ) : trips.length ? (
            <ul className="divide-y divide-border">
              {trips.slice(0, 4).map((trip) => (
                <li
                  key={trip.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3"
                >
                  <div>
                    <p className="font-medium">{trip.destination}</p>
                    <p className="text-xs text-muted-foreground">
                      {trip.start_date} – {trip.end_date}
                    </p>
                  </div>
                  <p className="text-sm font-medium">₹{trip.budget.toLocaleString("en-IN")}</p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No trips planned yet."
              description="Start a trip plan and it will appear here."
              action={
                <Button asChild>
                  <Link to="/app/planner">Plan your first trip</Link>
                </Button>
              }
            />
          )}
        </section>

        <section className="surface space-y-4 p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">Your travel profile</h2>
            <Button asChild variant="ghost" size="icon" aria-label="Edit preferences">
              <Link to="/app/settings">
                <Settings className="h-4 w-4" />
              </Link>
            </Button>
          </div>
          {preferences?.interests.length ? (
            <div className="flex flex-wrap gap-2">
              {preferences.interests.map((interest) => (
                <span key={interest} className="rounded-full bg-muted px-3 py-1 text-xs">
                  {interest}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              You haven&apos;t added travel interests yet.
            </p>
          )}
          <Button asChild variant="outline" className="w-full">
            <Link to="/app/settings">Manage preferences</Link>
          </Button>
        </section>
      </div>
    </div>
  );
}
