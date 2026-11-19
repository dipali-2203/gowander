import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { BedDouble, ExternalLink, MapPin, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader, EmptyState } from "@/components/travel/PageHeader";
import { HotelCard } from "@/components/travel/HotelCard";
import { HotelLocationMap, type HotelMapAttraction } from "@/components/travel/HotelLocationMap";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  getHotelRecommendations,
  getAttractionCatalog,
  getUserTrips,
  removeTripAccommodation,
  selectTripAccommodation,
  type AccountTrip,
  type HotelRecommendation,
  type HotelRecommendations,
  type AttractionCatalog,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/app/hotels")({
  validateSearch: (search: Record<string, unknown>) => ({
    tripId:
      Number.isInteger(Number(search["tripId"])) && Number(search["tripId"]) > 0
        ? Number(search["tripId"])
        : undefined,
  }),
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Hotels · GoWander" },
      {
        name: "description",
        content: "OpenStreetMap lodging recommendations ranked against a saved itinerary.",
      },
      { property: "og:title", content: "Hotels · GoWander" },
      {
        property: "og:description",
        content: "Stays ranked by distance to planned activities and available sourced details.",
      },
    ],
  }),
  component: Hotels,
});

const filters = ["All", "Budget", "Luxury", "Family", "Business", "Couples"] as const;

function Hotels() {
  const { tripId: requestedTripId } = Route.useSearch();
  const [trips, setTrips] = useState<AccountTrip[]>([]);
  const [tripsLoading, setTripsLoading] = useState(true);
  const [selectedTripId, setSelectedTripId] = useState<number | null>(null);
  const [data, setData] = useState<HotelRecommendations | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<(typeof filters)[number]>("All");
  const [detail, setDetail] = useState<HotelRecommendation | null>(null);
  const [savingHotelId, setSavingHotelId] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const [attractionCatalog, setAttractionCatalog] = useState<AttractionCatalog | null>(null);
  const [activeHotelId, setActiveHotelId] = useState<string | null>(null);
  const hotelCardRefs = useMemo(() => new Map<string, HTMLElement>(), []);

  useEffect(() => {
    let active = true;
    getUserTrips()
      .then((items) => {
        if (!active) return;
        setTrips(items);
        const requested = items.find(
          (item) => item.id === requestedTripId && item.latest_itinerary,
        );
        setSelectedTripId(requested?.id ?? items.find((item) => item.latest_itinerary)?.id ?? null);
      })
      .catch((cause) => {
        if (active)
          setError(cause instanceof Error ? cause.message : "Could not load your saved trips.");
      })
      .finally(() => {
        if (active) setTripsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [requestedTripId]);

  const loadRecommendations = async (tripId: number) => {
    setLoading(true);
    setError(null);
    try {
      setData(await getHotelRecommendations(tripId));
    } catch (cause) {
      setData(null);
      setError(cause instanceof Error ? cause.message : "Could not load hotel recommendations.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const selectedTrip = trips.find((trip) => trip.id === selectedTripId);
    if (selectedTripId !== null && selectedTrip?.latest_itinerary) {
      void loadRecommendations(selectedTripId);
    } else {
      setData(null);
      setError(null);
    }
  }, [selectedTripId, trips]);

  const results = useMemo(
    () =>
      (data?.items ?? []).filter((hotel) => filter === "All" || hotel.filter_tags.includes(filter)),
    [data, filter],
  );

  const addHotel = async (hotel: HotelRecommendation) => {
    if (!selectedTripId) return;
    setSavingHotelId(hotel.id);
    try {
      await selectTripAccommodation(selectedTripId, hotel.id);
      toast.success(`${hotel.name} selected as accommodation for this trip.`);
      await loadRecommendations(selectedTripId);
      setTrips(await getUserTrips());
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not save the selected hotel.");
    } finally {
      setSavingHotelId(null);
    }
  };

  const removeHotel = async () => {
    if (!selectedTripId) return;
    setRemoving(true);
    try {
      await removeTripAccommodation(selectedTripId);
      toast.success("Selected accommodation removed. The configured budget allowance is retained.");
      await loadRecommendations(selectedTripId);
      setTrips(await getUserTrips());
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not remove the selected hotel.");
    } finally {
      setRemoving(false);
    }
  };

  const currentTrip = trips.find((trip) => trip.id === selectedTripId);
  const selected = data?.selected_accommodation;

  useEffect(() => {
    let active = true;
    setAttractionCatalog(null);
    setActiveHotelId(null);
    if (!currentTrip?.latest_itinerary) return;
    getAttractionCatalog(currentTrip.destination)
      .then((catalog) => {
        if (active) setAttractionCatalog(catalog);
      })
      .catch(() => {
        if (active) setAttractionCatalog(null);
      });
    return () => {
      active = false;
    };
  }, [
    currentTrip?.id,
    currentTrip?.destination,
    currentTrip?.itinerary_revision,
    currentTrip?.latest_itinerary,
  ]);

  const plannedAttractions = useMemo<HotelMapAttraction[]>(() => {
    if (
      !currentTrip?.latest_itinerary ||
      !attractionCatalog ||
      attractionCatalog.data_source === "synthetic"
    ) {
      return [];
    }
    const scheduledIds = new Set(
      currentTrip.latest_itinerary.days.flatMap((day) =>
        day.stops.map((stop) => stop.attraction_id),
      ),
    );
    return attractionCatalog.attractions
      .filter(
        (attraction) => scheduledIds.has(attraction.id) && attraction.data_source !== "synthetic",
      )
      .map((attraction) => ({
        id: attraction.id,
        name: attraction.name,
        category: attraction.catalog_category ?? attraction.category,
        latitude: attraction.latitude,
        longitude: attraction.longitude,
        source_url: attraction.source_url ?? null,
        attribution: attraction.attribution ?? null,
      }));
  }, [currentTrip?.latest_itinerary, attractionCatalog]);

  const focusHotel = (hotelId: string) => {
    setActiveHotelId(hotelId);
    requestAnimationFrame(() => {
      hotelCardRefs.get(hotelId)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Stays along your route"
        description="Ranked against all planned visits, your saved-trip accommodation budget, and available preferences. Distances are straight-line estimates."
      />

      {error && trips.length === 0 && !tripsLoading ? (
        <p className="surface p-4 text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : tripsLoading ? (
        <p className="surface p-4 text-sm text-muted-foreground" role="status">
          Loading saved trips…
        </p>
      ) : trips.length === 0 ? (
        <EmptyState
          icon={<BedDouble className="h-5 w-5" />}
          title="Choose a saved trip first"
          description="Hotel recommendations use a saved multi-day itinerary and its planned attractions."
          action={
            <Button asChild>
              <Link to="/app/planner">Plan a trip</Link>
            </Button>
          }
        />
      ) : (
        <>
          <label className="flex flex-wrap items-center gap-3 text-sm">
            Saved trip
            <select
              aria-label="Select saved trip for hotel recommendations"
              className="min-w-64 rounded-md border border-input bg-background px-3 py-2"
              value={selectedTripId ?? ""}
              onChange={(event) => setSelectedTripId(Number(event.target.value))}
            >
              {trips.map((trip) => (
                <option key={trip.id} value={trip.id}>
                  {trip.name} · {trip.destination}
                </option>
              ))}
            </select>
          </label>

          {!selectedTripId ? (
            <EmptyState
              icon={<BedDouble className="h-5 w-5" />}
              title="No saved itinerary is available"
              description="Generate and save a trip itinerary first. Hotel recommendations never use a random route."
              action={
                <Button asChild>
                  <Link to="/app/planner">Plan a trip</Link>
                </Button>
              }
            />
          ) : null}

          {currentTrip && !currentTrip.latest_itinerary ? (
            <EmptyState
              icon={<BedDouble className="h-5 w-5" />}
              title="This trip has no saved itinerary yet"
              description="Generate an itinerary with attraction locations before viewing route-aware stays."
              action={
                <Button asChild>
                  <Link to="/app/planner">Plan this trip</Link>
                </Button>
              }
            />
          ) : null}

          {selected ? (
            <section className="surface flex flex-wrap items-center justify-between gap-4 p-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-primary">
                  Selected accommodation
                </p>
                <h2 className="mt-1 font-semibold">{selected.name}</h2>
                <p className="text-sm text-muted-foreground">
                  {selected.nightly_price === null
                    ? "Nightly price unavailable; existing configured accommodation allowance retained."
                    : `${selected.price_currency} ${selected.nightly_price.toLocaleString("en-IN")} per room/night · sourced listing, not a booking quote.`}
                </p>
              </div>
              <Button variant="outline" disabled={removing} onClick={() => void removeHotel()}>
                <Trash2 className="h-4 w-4" /> {removing ? "Removing…" : "Remove stay"}
              </Button>
            </section>
          ) : null}

          <div className="flex flex-wrap gap-2" aria-label="Hotel filters">
            {filters.map((item) => (
              <button
                key={item}
                type="button"
                aria-pressed={filter === item}
                onClick={() => setFilter(item)}
                className={cn(
                  "rounded-full border px-4 py-1.5 text-sm transition-colors",
                  filter === item
                    ? "border-primary bg-primary-soft text-primary"
                    : "border-border hover:bg-muted",
                )}
              >
                {item}
              </button>
            ))}
          </div>

          {error ? (
            <p className="surface p-4 text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          {loading ? (
            <p className="surface p-4 text-sm text-muted-foreground" role="status">
              Finding stays for your itinerary…
            </p>
          ) : null}

          {!loading && !error && data && data.items.length === 0 ? (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
              <EmptyState
                icon={<BedDouble className="h-5 w-5" />}
                title={`No sourced hotel inventory for ${data.trip.destination}`}
                description="No OSM lodging records have been imported for this destination. GoWander will not fill the list with demonstration properties."
              />
              <aside className="surface-static overflow-hidden">
                <div className="p-3 sm:p-4">
                  <p className="mb-3 text-sm font-medium">
                    {data.trip.destination} · planned visits
                  </p>
                  <HotelLocationMap
                    hotels={[]}
                    attractions={plannedAttractions}
                    selectedHotelId={null}
                    activeHotelId={null}
                    mapKey={String(selectedTripId)}
                    onSelectHotel={focusHotel}
                  />
                </div>
              </aside>
            </div>
          ) : null}

          {!loading && !error && data && data.items.length > 0 && results.length === 0 ? (
            <EmptyState
              icon={<BedDouble className="h-5 w-5" />}
              title="No sourced stays match that filter"
              description="Filters use explicit OpenStreetMap hotel tags and mapped stars only."
              action={<Button onClick={() => setFilter("All")}>Reset filters</Button>}
            />
          ) : null}

          {!loading && !error && data && results.length > 0 ? (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(380px,500px)]">
              <div className="grid content-start gap-4 sm:grid-cols-2">
                {results.map((hotel) => (
                  <div
                    key={hotel.id}
                    ref={(element) => {
                      if (element) hotelCardRefs.set(hotel.id, element);
                      else hotelCardRefs.delete(hotel.id);
                    }}
                    onMouseEnter={() => setActiveHotelId(hotel.id)}
                  >
                    <HotelCard
                      hotel={hotel}
                      adding={savingHotelId === hotel.id}
                      onView={setDetail}
                      onAdd={(item) => void addHotel(item)}
                    />
                  </div>
                ))}
              </div>
              <aside className="surface-static overflow-hidden xl:sticky xl:top-24 xl:self-start">
                <div className="p-3 sm:p-4">
                  <p className="mb-3 text-sm font-medium">
                    {data.trip.destination} · stays and planned visits
                  </p>
                  <HotelLocationMap
                    hotels={results}
                    attractions={plannedAttractions}
                    selectedHotelId={data.selected_accommodation?.hotel_id ?? null}
                    activeHotelId={activeHotelId}
                    mapKey={String(selectedTripId)}
                    onSelectHotel={focusHotel}
                  />
                  <p className="mt-2 text-xs text-muted-foreground">
                    {results.length} sourced stay(s) · {plannedAttractions.length} mapped planned
                    attraction(s)
                  </p>
                </div>
              </aside>
            </div>
          ) : null}

          {data?.attribution ? (
            <p className="text-xs text-muted-foreground">{data.attribution} · ODbL</p>
          ) : null}
          {selectedTripId !== null && data ? (
            <p className="text-xs text-muted-foreground">
              {data.trip.nights} night(s) ·{" "}
              {data.trip.traveler_count ?? "Traveler count unavailable"} traveler(s) · Budget INR{" "}
              {data.trip.budget.toLocaleString("en-IN")}
            </p>
          ) : null}
        </>
      )}

      <Dialog
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
          {detail ? (
            <>
              <DialogHeader>
                <DialogTitle>{detail.name}</DialogTitle>
                <DialogDescription className="capitalize">
                  {detail.hotel_type.replaceAll("_", " ")} in {detail.destination}
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 text-sm">
                <p>{detail.address ?? "Address unavailable in source data."}</p>
                <p>
                  {detail.nightly_price === null
                    ? "Nightly price unavailable. No booking provider is connected."
                    : `${detail.price_currency} ${detail.nightly_price.toLocaleString("en-IN")} per room/night · ${detail.price_source ?? "Source price"}. Not a booking quote.`}
                </p>
                <p>
                  {detail.stars === null
                    ? "Mapped hotel stars unavailable. Guest ratings and review counts are not provided."
                    : `${detail.stars} stars mapped in OpenStreetMap; this is a property classification, not a guest rating.`}
                </p>
                <p>
                  Website:{" "}
                  {detail.website ? (
                    <a className="underline" href={detail.website} target="_blank" rel="noreferrer">
                      {detail.website}
                    </a>
                  ) : (
                    "unavailable"
                  )}
                </p>
                <p>Contact: {detail.phone ?? "unavailable"}</p>
                <p>Brand/operator: {detail.brand ?? "unavailable"}</p>
                <p>
                  Distance:{" "}
                  {detail.average_distance_km === null
                    ? "unavailable"
                    : `${detail.average_distance_km.toFixed(1)} km average straight-line distance across scheduled visits`}
                  .
                  {detail.nearest_distance_km === null
                    ? ""
                    : ` Nearest planned visit: ${detail.nearest_distance_km.toFixed(1)} km.`}
                </p>
                <div>
                  <h3 className="font-medium">Why this match?</h3>
                  {detail.reasons.length ? (
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
                      {detail.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground">
                      No supported match factors are available.
                    </p>
                  )}
                </div>
                <div>
                  <h3 className="font-medium">Score components</h3>
                  <ul className="mt-1 space-y-1 text-xs text-muted-foreground">
                    {Object.entries(detail.factor_scores).map(([factor, score]) => (
                      <li key={factor} className="flex justify-between gap-4">
                        <span className="capitalize">
                          {factor} ({Math.round((data?.factor_weights[factor] ?? 0) * 100)}%
                          configured weight)
                        </span>
                        <span>{score === null ? "Unavailable" : `${score.toFixed(0)}/100`}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-xs text-muted-foreground">{data?.score_note}</p>
                </div>
                <p>
                  Freshness:{" "}
                  {detail.last_fetched_at
                    ? new Date(detail.last_fetched_at).toLocaleString()
                    : "unknown"}
                </p>
                <p>
                  Dataset: {detail.source_dataset ?? "unavailable"} · License:{" "}
                  {detail.license_name ?? "unavailable"}
                </p>
                {detail.source_url ? (
                  <p>
                    {detail.attribution} ·{" "}
                    <a
                      className="underline"
                      href={detail.source_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open source object
                    </a>
                  </p>
                ) : null}
                <p className="text-xs text-muted-foreground">
                  GoWander does not provide booking availability. Contact or visit the property
                  website directly.
                </p>
                <a
                  className="inline-flex items-center gap-2 text-primary underline"
                  href={`https://www.openstreetmap.org/?mlat=${detail.latitude}&mlon=${detail.longitude}#map=17/${detail.latitude}/${detail.longitude}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <MapPin className="h-4 w-4" /> Map location{" "}
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
