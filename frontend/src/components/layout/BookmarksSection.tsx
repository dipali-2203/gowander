import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";
import { Bookmark, Compass, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/travel/PageHeader";
import { destinations } from "@/data/destinations";
import {
  getAttractionCatalog,
  getBookmarks,
  removeBookmark,
  type AttractionInput,
} from "@/lib/api";

type ResolvedPoi = AttractionInput & { city: string; state: string };

export function BookmarksSection() {
  const [ids, setIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [resolvedPois, setResolvedPois] = useState<Map<string, ResolvedPoi>>(new Map());
  const [catalogWarning, setCatalogWarning] = useState(false);

  async function refresh() {
    const result = await getBookmarks();
    setIds(result.items.map((item) => item.destination_id));
  }

  useEffect(() => {
    let active = true;
    getBookmarks()
      .then(async (result) => {
        if (!active) return;
        const bookmarkIds = result.items.map((item) => item.destination_id);
        setIds(bookmarkIds);
        const hasOsmBookmarks = bookmarkIds.some((id) => /^osm:(node|way|relation):\d+$/i.test(id));
        if (!hasOsmBookmarks) return;

        const catalogs = await Promise.allSettled([
          getAttractionCatalog("jaipur"),
          getAttractionCatalog("udaipur"),
        ]);
        if (!active) return;
        const matches = new Map<string, ResolvedPoi>();
        let hadCatalogError = false;
        catalogs.forEach((result, index) => {
          if (result.status === "rejected") {
            hadCatalogError = true;
            return;
          }
          const city = index === 0 ? "Jaipur" : "Udaipur";
          result.value.attractions.forEach((attraction) => {
            if (bookmarkIds.includes(attraction.id)) {
              matches.set(attraction.id, {
                ...attraction,
                city,
                state: "Rajasthan",
              });
            }
          });
        });
        setResolvedPois(matches);
        setCatalogWarning(hadCatalogError);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load bookmarks.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function remove(id: string) {
    setRemoving(id);
    try {
      await removeBookmark(id);
      setIds((current) => current.filter((item) => item !== id));
      toast.success("Bookmark removed.");
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not remove bookmark.");
      await refresh();
    } finally {
      setRemoving(null);
    }
  }

  if (loading)
    return (
      <div className="surface p-6 text-sm text-muted-foreground" role="status">
        Loading your bookmarks…
      </div>
    );
  if (error)
    return (
      <div className="surface p-6 text-sm text-destructive" role="alert">
        {error}
      </div>
    );
  if (ids.length === 0) {
    return (
      <EmptyState
        icon={<Bookmark className="h-5 w-5" />}
        title="No saved destinations yet."
        description="Explore destinations and bookmark the places you'd love to visit."
        action={
          <Button asChild>
            <Link to="/app/explore">
              <Compass className="mr-2 h-4 w-4" />
              Explore destinations
            </Link>
          </Button>
        }
      />
    );
  }

  return (
    <section className="grid gap-4 sm:grid-cols-2">
      {catalogWarning && (
        <p className="surface p-4 text-sm text-muted-foreground sm:col-span-2" role="status">
          Some attraction details could not be loaded. You can still remove those bookmarks.
        </p>
      )}
      {ids.map((id) => {
        const destination = destinations.find((item) => item.id === id);
        const poi = resolvedPois.get(id);
        return (
          <article key={id} className="surface flex items-center gap-4 p-4">
            {destination && (
              <img
                src={destination.image}
                alt=""
                loading="lazy"
                className="h-16 w-16 shrink-0 rounded-xl object-cover"
              />
            )}
            <div className="min-w-0 flex-1">
              <h3 className="truncate font-medium">
                {destination?.name ?? poi?.name ?? "Attraction details unavailable"}
              </h3>
              <p className="truncate text-sm text-muted-foreground">
                {destination
                  ? destination.state
                  : poi
                    ? `${poi.category} · ${poi.city}, ${poi.state}`
                    : "Saved attraction · Location details unavailable"}
              </p>
              {poi && (
                <a
                  className="mt-1 inline-block text-sm text-primary underline underline-offset-2"
                  href={`/app/explore?destination=${encodeURIComponent(poi.city.toLowerCase())}&attractionId=${encodeURIComponent(id)}`}
                >
                  View in Explore
                </a>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${destination?.name ?? poi?.name ?? "unresolved attraction"} bookmark`}
              disabled={removing === id}
              onClick={() => void remove(id)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </article>
        );
      })}
    </section>
  );
}
