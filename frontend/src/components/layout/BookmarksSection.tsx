import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";
import { Bookmark, Compass, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/travel/PageHeader";
import { destinations } from "@/data/destinations";
import { getBookmarks, removeBookmark } from "@/lib/api";

export function BookmarksSection() {
  const [ids, setIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  async function refresh() {
    const result = await getBookmarks();
    setIds(result.items.map((item) => item.destination_id));
  }

  useEffect(() => {
    let active = true;
    getBookmarks()
      .then((result) => {
        if (active) setIds(result.items.map((item) => item.destination_id));
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
      {ids.map((id) => {
        const destination = destinations.find((item) => item.id === id);
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
              <h3 className="truncate font-medium">{destination?.name ?? id}</h3>
              <p className="truncate text-sm text-muted-foreground">
                {destination?.state ?? "Saved destination"}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${destination?.name ?? id} bookmark`}
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
