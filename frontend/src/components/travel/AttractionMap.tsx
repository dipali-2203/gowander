import { useEffect, useState } from "react";
import type { AttractionInput } from "@/lib/api";

type LeafletMapModule = typeof import("./LeafletAttractionMap");

type Props = {
  city: string;
  attractions: AttractionInput[];
  selectedId: string | null;
  bookmarkedIds: string[];
  bookmarkBusyId: string | null;
  dataset: string | null;
  attribution: string | null;
  onSelect: (id: string) => void;
  onBookmark: (id: string, name: string) => void;
};

export function AttractionMap(props: Props) {
  const [mapModule, setMapModule] = useState<LeafletMapModule | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let active = true;
    import("./LeafletAttractionMap")
      .then((module) => {
        if (active) setMapModule(() => module);
      })
      .catch(() => {
        if (active) setLoadFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="relative h-[420px] min-h-[360px] overflow-hidden rounded-xl border border-border bg-muted/40 sm:h-[520px] xl:h-[min(72vh,760px)]">
      {mapModule ? (
        <mapModule.LeafletAttractionMap {...props} />
      ) : loadFailed ? (
        <div
          className="grid h-full place-items-center p-6 text-center text-sm text-destructive"
          role="alert"
        >
          The interactive map could not be loaded. Attraction details are still available in the
          list.
        </div>
      ) : (
        <div
          className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground"
          role="status"
        >
          Loading interactive attraction map…
        </div>
      )}
    </div>
  );
}
