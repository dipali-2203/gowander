import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Search, Sparkles, X, Plus, Bookmark, BookmarkCheck } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/travel/PageHeader";
import { DestinationCard } from "@/components/travel/DestinationCard";
import { IndiaMap } from "@/components/travel/IndiaMap";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { destinations, states, categories, type Destination } from "@/data/destinations";
import { useTripStore } from "@/store/trip";
import {
  addBookmark,
  getAttractionCatalog,
  getBookmarks,
  removeBookmark,
  type AttractionCatalog,
} from "@/lib/api";

export const Route = createFileRoute("/app/explore")({
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Explore India · GoWander" },
      {
        name: "description",
        content:
          "Browse an interactive map of India, filter destinations by state, category, budget and duration, and add them to your trip.",
      },
      { property: "og:title", content: "Explore India · GoWander" },
      {
        property: "og:description",
        content: "An interactive destination explorer for planning trips across India.",
      },
    ],
  }),
  component: Explore,
});

function Explore() {
  const [query, setQuery] = useState("");
  const [state, setState] = useState("all");
  const [category, setCategory] = useState("all");
  const [budget, setBudget] = useState("all");
  const [duration, setDuration] = useState("all");
  const [active, setActive] = useState<Destination | null>(null);
  const [bookmarkedIds, setBookmarkedIds] = useState<string[]>([]);
  const [bookmarkBusy, setBookmarkBusy] = useState<string | null>(null);
  const [attractionCity, setAttractionCity] = useState("jaipur");
  const [attractionCatalog, setAttractionCatalog] = useState<AttractionCatalog | null>(null);
  const [attractionLoading, setAttractionLoading] = useState(true);
  const [poiQuery, setPoiQuery] = useState("");
  const [poiCategory, setPoiCategory] = useState("All");
  const [browseAllPois, setBrowseAllPois] = useState(false);
  const add = useTripStore((s) => s.add);

  useEffect(() => {
    getBookmarks()
      .then(({ items }) => setBookmarkedIds(items.map((item) => item.destination_id)))
      .catch(() => {
        toast.error("Could not load your saved destinations.");
      });
  }, []);

  useEffect(() => {
    let active = true;
    setAttractionLoading(true);
    getAttractionCatalog(attractionCity)
      .then((catalog) => {
        if (active) setAttractionCatalog(catalog);
      })
      .catch(() => {
        if (active) setAttractionCatalog(null);
      })
      .finally(() => {
        if (active) setAttractionLoading(false);
      });
    return () => {
      active = false;
    };
  }, [attractionCity]);

  const results = useMemo(
    () =>
      destinations.filter((d) => {
        const q = query.trim().toLowerCase();
        const days = parseInt(d.duration, 10) || 1;
        return (
          (!q || d.name.toLowerCase().includes(q) || d.state.toLowerCase().includes(q)) &&
          (state === "all" || d.state === state) &&
          (category === "all" || d.category === category) &&
          (budget === "all" || d.budgetBand === budget) &&
          (duration === "all" ||
            (duration === "short" && days <= 2) ||
            (duration === "mid" && days > 2 && days <= 5) ||
            (duration === "long" && days > 5))
        );
      }),
    [query, state, category, budget, duration],
  );

  const onAdd = (d: Destination) => {
    add(d);
    toast.success(`${d.name} added to your trip`);
  };

  const onBookmark = async (d: Destination) => {
    if (bookmarkBusy) return;
    setBookmarkBusy(d.id);
    const alreadyBookmarked = bookmarkedIds.includes(d.id);
    try {
      if (alreadyBookmarked) {
        await removeBookmark(d.id);
        setBookmarkedIds((current) => current.filter((id) => id !== d.id));
        toast.success(`${d.name} removed from bookmarks`);
      } else {
        await addBookmark(d.id);
        setBookmarkedIds((current) => [...current, d.id]);
        toast.success(`${d.name} saved to bookmarks`);
      }
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not update your bookmarks.");
      getBookmarks()
        .then(({ items }) => setBookmarkedIds(items.map((item) => item.destination_id)))
        .catch(() => undefined);
    } finally {
      setBookmarkBusy(null);
    }
  };

  const onPoiBookmark = async (id: string, name: string) => {
    if (bookmarkBusy) return;
    setBookmarkBusy(id);
    try {
      if (bookmarkedIds.includes(id)) {
        await removeBookmark(id);
        setBookmarkedIds((current) => current.filter((item) => item !== id));
        toast.success(`${name} removed from bookmarks`);
      } else {
        await addBookmark(id);
        setBookmarkedIds((current) => [...current, id]);
        toast.success(`${name} saved to bookmarks`);
      }
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not update your bookmarks.");
    } finally {
      setBookmarkBusy(null);
    }
  };

  const poiCategories = [
    "Park",
    "Religious",
    "Viewpoint",
    "Cultural",
    "Historical",
    "Museum",
    "Entertainment",
    "Other",
  ];
  const poiResults = (attractionCatalog?.attractions ?? [])
    .filter((place) => {
      const placeCategory = (place.catalog_category ?? place.category).toLowerCase();
      const q = poiQuery.trim().toLowerCase();
      return (
        (poiCategory === "All" || placeCategory === poiCategory.toLowerCase()) &&
        (!q || place.name.toLowerCase().includes(q) || placeCategory.includes(q))
      );
    })
    .sort(
      (a, b) =>
        (b.priority_score ?? b.preference_score) - (a.priority_score ?? a.preference_score) ||
        a.name.localeCompare(b.name),
    );

  return (
    <div className="space-y-5">
      <PageHeader
        title="Explore India"
        description="Pan the map, filter by what you actually care about, and build a shortlist."
      />

      <section className="surface space-y-4 p-5" aria-labelledby="attraction-catalog-title">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 id="attraction-catalog-title" className="text-lg font-semibold">
              Attraction catalog
            </h2>
            <p className="text-sm text-muted-foreground">
              Planning relevance uses category and available OSM tags. It is not popularity or a
              rating.
            </p>
          </div>
          <div className="flex gap-2">
            {["jaipur", "udaipur"].map((city) => (
              <Button
                key={city}
                size="sm"
                variant={attractionCity === city ? "default" : "outline"}
                onClick={() => {
                  setAttractionCity(city);
                  setPoiQuery("");
                  setPoiCategory("All");
                  setBrowseAllPois(false);
                }}
              >
                {city[0]?.toUpperCase()}
                {city.slice(1)}
              </Button>
            ))}
          </div>
        </div>
        {attractionLoading ? (
          <p className="text-sm text-muted-foreground">Loading saved catalog…</p>
        ) : !attractionCatalog ? (
          <p className="text-sm text-muted-foreground">
            Could not load this destination's catalog.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="secondary">
                {attractionCatalog.data_source === "osm"
                  ? "OpenStreetMap"
                  : attractionCatalog.data_source}
              </Badge>
              <Badge variant="secondary">
                {attractionCatalog.catalog_status.replaceAll("_", " ")}
              </Badge>
              {attractionCatalog.attribution && (
                <span className="text-muted-foreground">{attractionCatalog.attribution}</span>
              )}
            </div>
            {attractionCatalog.message && (
              <p className="text-sm text-amber-700">{attractionCatalog.message}</p>
            )}
            {attractionCatalog.attractions.length ? (
              <div className="space-y-4">
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Input
                    aria-label="Search attractions"
                    placeholder={`Search ${attractionCity} attractions`}
                    value={poiQuery}
                    onChange={(event) => setPoiQuery(event.target.value)}
                  />
                  <Button variant="outline" onClick={() => setBrowseAllPois((value) => !value)}>
                    {browseAllPois
                      ? "Show featured"
                      : `Browse all ${attractionCatalog.attractions.length}`}
                  </Button>
                </div>
                <div className="flex flex-wrap gap-2" aria-label="Attraction category filters">
                  {["All", ...poiCategories].map((item) => {
                    const count =
                      item === "All"
                        ? attractionCatalog.attractions.length
                        : attractionCatalog.attractions.filter(
                            (place) =>
                              (place.catalog_category ?? place.category).toLowerCase() ===
                              item.toLowerCase(),
                          ).length;
                    return (
                      <Button
                        key={item}
                        size="sm"
                        variant={poiCategory === item ? "default" : "outline"}
                        onClick={() => {
                          setPoiCategory(item);
                          setBrowseAllPois(true);
                        }}
                      >
                        {item} ({count})
                      </Button>
                    );
                  })}
                </div>
                <h3 className="text-sm font-semibold">
                  {browseAllPois || poiQuery || poiCategory !== "All"
                    ? `${poiResults.length} matching attractions`
                    : "Featured recommendations"}
                </h3>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {(browseAllPois || poiQuery || poiCategory !== "All"
                    ? poiResults
                    : poiResults.slice(0, 6)
                  ).map((place) => (
                    <article key={place.id} className="rounded-lg border border-border p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <h3 className="truncate text-sm font-medium">{place.name}</h3>
                          <p className="text-xs capitalize text-muted-foreground">
                            {place.catalog_category ?? place.category} · Planning relevance{" "}
                            {Math.round((place.priority_score ?? place.preference_score) * 100)}%
                          </p>
                        </div>
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label={`${bookmarkedIds.includes(place.id) ? "Remove" : "Save"} ${place.name} bookmark`}
                          aria-pressed={bookmarkedIds.includes(place.id)}
                          disabled={bookmarkBusy === place.id}
                          onClick={() => void onPoiBookmark(place.id, place.name)}
                        >
                          {bookmarkedIds.includes(place.id) ? (
                            <BookmarkCheck className="h-4 w-4" />
                          ) : (
                            <Bookmark className="h-4 w-4" />
                          )}
                        </Button>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Fee: {place.cost_known ? `₹${place.cost}` : "Unknown"} · Duration:{" "}
                        {place.visit_duration_known ? `${place.visit_minutes} min` : "Unknown"}
                      </p>
                      <details className="mt-2 text-xs">
                        <summary className="cursor-pointer text-primary">More data</summary>
                        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1">
                          <dt>Hours</dt>
                          <dd>{place.opening_window_known ? place.opening_hours : "Unknown"}</dd>
                          <dt>Coordinates</dt>
                          <dd>
                            {place.latitude.toFixed(5)}, {place.longitude.toFixed(5)}
                          </dd>
                          <dt>Record</dt>
                          <dd>
                            {(place.verification_status ?? "unknown").replaceAll("_", " ")};{" "}
                            {place.data_freshness ?? "freshness unknown"}
                          </dd>
                          <dt>Dataset</dt>
                          <dd>{place.source_dataset ?? "Source dataset unknown"}</dd>
                          <dt>License</dt>
                          <dd>{place.license_name ?? "Unknown"}</dd>
                          <dt>Recommendation basis</dt>
                          <dd>
                            {place.priority_reasons?.join("; ") ||
                              "Category-based relevance heuristic"}
                          </dd>
                        </dl>
                        {place.source_url && (
                          <a
                            className="mt-2 inline-block text-primary underline"
                            href={place.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open source record
                          </a>
                        )}
                      </details>
                    </article>
                  ))}
                </div>
                {attractionCatalog.attribution && (
                  <p className="text-xs text-muted-foreground">
                    {attractionCatalog.attribution}. Dataset and license are shown with each
                    attraction record.
                  </p>
                )}
                {!poiResults.length && (
                  <p className="text-sm text-muted-foreground">
                    No attractions match this search or category.
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No imported attraction records are available for this city.
              </p>
            )}
          </>
        )}
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <div className="relative h-[420px] xl:sticky xl:top-24 xl:h-[calc(100dvh-140px)]">
          <div className="surface h-full overflow-hidden p-2">
            <IndiaMap active={active?.id ?? null} onSelect={setActive} />
          </div>

          <AnimatePresence>
            {active && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 20 }}
                className="surface absolute bottom-4 left-4 right-4 flex gap-4 p-4"
              >
                <img
                  src={active.image}
                  alt={active.name}
                  className="h-24 w-24 shrink-0 rounded-xl object-cover"
                />
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="truncate font-semibold">{active.name}</h3>
                      <p className="truncate text-xs text-muted-foreground">{active.state}</p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Close destination details"
                      onClick={() => setActive(null)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                  <p className="line-clamp-2 text-xs text-muted-foreground">{active.description}</p>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge variant="secondary">{active.bestTime}</Badge>
                    <Badge variant="secondary">{active.duration}</Badge>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" className="mt-1" onClick={() => onAdd(active)}>
                      <Plus className="h-4 w-4" /> Add to trip
                    </Button>
                    <Button
                      size="icon"
                      variant="outline"
                      className="mt-1"
                      aria-pressed={bookmarkedIds.includes(active.id)}
                      aria-label={
                        bookmarkedIds.includes(active.id)
                          ? `Remove ${active.name} bookmark`
                          : `Bookmark ${active.name}`
                      }
                      disabled={bookmarkBusy === active.id}
                      onClick={() => void onBookmark(active)}
                    >
                      {bookmarkedIds.includes(active.id) ? (
                        <BookmarkCheck className="h-4 w-4" />
                      ) : (
                        <Bookmark className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {!active && (
            <motion.aside
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              className="surface absolute bottom-4 right-4 max-w-[260px] space-y-1.5 p-4"
            >
              <span className="flex items-center gap-2 text-xs font-semibold text-primary">
                <Sparkles className="h-3.5 w-3.5" /> AI recommendation
              </span>
              <p className="text-sm">
                Pair <strong>Hampi</strong> with <strong>Goa</strong> — a 5-hour drive links ruins
                and coastline in one 6-day loop.
              </p>
            </motion.aside>
          )}
        </div>

        <div className="space-y-4">
          <div className="surface space-y-3 p-4">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search destinations or states"
                aria-label="Search destinations"
                className="pl-9"
              />
            </div>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <Select value={state} onValueChange={setState}>
                <SelectTrigger aria-label="Filter by state">
                  <SelectValue placeholder="State" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All states</SelectItem>
                  {states.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger aria-label="Filter by category">
                  <SelectValue placeholder="Category" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All categories</SelectItem>
                  {categories.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={budget} onValueChange={setBudget}>
                <SelectTrigger aria-label="Filter by budget">
                  <SelectValue placeholder="Budget" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Any budget</SelectItem>
                  <SelectItem value="Budget">Budget</SelectItem>
                  <SelectItem value="Moderate">Moderate</SelectItem>
                  <SelectItem value="Premium">Premium</SelectItem>
                </SelectContent>
              </Select>
              <Select value={duration} onValueChange={setDuration}>
                <SelectTrigger aria-label="Filter by duration">
                  <SelectValue placeholder="Duration" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Any length</SelectItem>
                  <SelectItem value="short">1–2 days</SelectItem>
                  <SelectItem value="mid">3–5 days</SelectItem>
                  <SelectItem value="long">6+ days</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <p className="text-xs text-muted-foreground">{results.length} destinations match</p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {results.map((d) => (
              <DestinationCard
                key={d.id}
                destination={d}
                onAdd={onAdd}
                onOpen={setActive}
                bookmarked={bookmarkedIds.includes(d.id)}
                onBookmark={onBookmark}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
