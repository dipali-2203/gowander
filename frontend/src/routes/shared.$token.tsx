import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { TripBudgetEstimatePanel } from "@/components/travel/TripBudgetEstimatePanel";
import { getSharedItinerary, type SharedItinerary } from "@/lib/api";

export const Route = createFileRoute("/shared/$token")({
  head: () => ({ meta: [{ title: "Shared itinerary · GoWander" }] }),
  component: SharedItineraryPage,
});

function clock(minute: number) {
  return `${String(Math.floor(minute / 60) % 24).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
}

function SharedItineraryPage() {
  const { token } = Route.useParams();
  const [trip, setTrip] = useState<SharedItinerary | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getSharedItinerary(token)
      .then((shared) => {
        if (active) setTrip(shared);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  return (
    <main className="min-h-screen bg-background px-4 py-8 sm:px-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <header className="flex items-center justify-between border-b border-border pb-4">
          <Link to="/" className="text-lg font-bold tracking-tight text-primary">
            GoWander
          </Link>
          <span className="text-xs text-muted-foreground">Shared read-only itinerary</span>
        </header>
        {loading ? (
          <p className="py-12 text-center text-sm text-muted-foreground">
            Loading shared itinerary…
          </p>
        ) : error || !trip ? (
          <section className="surface p-8 text-center" role="status">
            <h1 className="text-xl font-semibold">This shared itinerary is unavailable</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              The link may be invalid or its owner may have revoked it.
            </p>
            <Link to="/" className="mt-5 inline-block text-sm font-medium text-primary underline">
              Visit GoWander
            </Link>
          </section>
        ) : (
          <>
            <section className="surface space-y-2 p-6">
              <p className="text-xs font-semibold uppercase tracking-wide text-primary">
                Trip itinerary
              </p>
              <h1 className="text-2xl font-bold">{trip.title}</h1>
              <p className="text-sm text-muted-foreground">
                {[trip.origin, trip.destination].filter(Boolean).join(" → ")} · {trip.start_date} to{" "}
                {trip.end_date}
                {trip.traveler_count ? ` · ${trip.traveler_count} travelers` : ""}
              </p>
            </section>

            <ol className="space-y-4">
              {trip.days.map((day) => (
                <li key={`${day.day_number}-${day.date}`}>
                  <section className="surface overflow-hidden">
                    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-4">
                      <h2 className="font-semibold">
                        Day {day.day_number} · {day.date}
                      </h2>
                      <span className="text-xs text-muted-foreground">
                        {day.total_travel_minutes} min estimated travel
                      </span>
                    </header>
                    <div className="divide-y divide-border">
                      {day.stops.map((stop, index) => (
                        <article key={`${stop.name}-${index}`} className="p-4">
                          <p className="text-xs font-semibold text-primary">
                            {clock(stop.arrival_minute)}–{clock(stop.departure_minute)}
                          </p>
                          <h3 className="mt-1 font-medium">{stop.name}</h3>
                          <p className="text-sm text-muted-foreground">
                            {stop.visit_minutes} min visit · {stop.travel_minutes_before} min
                            estimated travel before
                          </p>
                          {stop.weather_advisories.map((advisory, advisoryIndex) => (
                            <p
                              key={`${advisory.type}-${advisoryIndex}`}
                              className="mt-2 rounded bg-muted p-2 text-xs"
                            >
                              Weather advisory{advisory.condition ? ` · ${advisory.condition}` : ""}
                              {advisory.forecast_time ? ` · ${advisory.forecast_time}` : ""}:{" "}
                              {advisory.description}
                            </p>
                          ))}
                        </article>
                      ))}
                      {day.meal_breaks.map((meal, index) => (
                        <article key={`${meal.start_minute}-${index}`} className="p-4 text-sm">
                          <p className="font-medium">Meal and rest break</p>
                          <p className="text-muted-foreground">
                            {clock(meal.start_minute)} · {meal.duration_minutes} min
                          </p>
                        </article>
                      ))}
                    </div>
                  </section>
                </li>
              ))}
            </ol>

            {trip.budget_estimate ? (
              <TripBudgetEstimatePanel
                estimate={trip.budget_estimate}
                completeBudgetCurrent={trip.budget_estimate.complete_budget_current === true}
                estimateIsCurrent={trip.budget_estimate.estimate_is_current !== false}
              />
            ) : null}
            {trip.selected_accommodation ? (
              <section className="surface space-y-2 p-5">
                <h2 className="font-semibold">Selected accommodation</h2>
                <p>
                  {trip.selected_accommodation.name} ·{" "}
                  {trip.selected_accommodation.hotel_type.replaceAll("_", " ")}
                </p>
                <p className="text-sm text-muted-foreground">
                  {trip.selected_accommodation.address ?? "Address unavailable"}
                </p>
                <p className="text-sm text-muted-foreground">
                  {trip.selected_accommodation.nightly_price === null
                    ? "Nightly price unavailable."
                    : `${trip.selected_accommodation.price_currency} ${trip.selected_accommodation.nightly_price.toLocaleString("en-IN")} per room/night; a source listing, not a booking quote.`}
                </p>
                {trip.selected_accommodation.source_url ? (
                  <a
                    className="text-xs underline"
                    href={trip.selected_accommodation.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {trip.selected_accommodation.attribution} ·{" "}
                    {trip.selected_accommodation.source_dataset ?? "OpenStreetMap"}
                  </a>
                ) : null}
              </section>
            ) : null}
            {trip.attributions.map((attribution) => (
              <p key={attribution} className="text-xs text-muted-foreground">
                {attribution}
              </p>
            ))}
            <footer className="border-t border-border pt-4 text-xs text-muted-foreground">
              Shared by a GoWander traveler · View only
            </footer>
          </>
        )}
      </div>
    </main>
  );
}
