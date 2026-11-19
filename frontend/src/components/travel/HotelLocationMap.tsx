import { useEffect, useState } from "react";
import type { AttractionInput, HotelRecommendation } from "@/lib/api";

type LeafletHotelMapModule = typeof import("./LeafletHotelLocationMap");

export type HotelMapAttraction = Pick<
  AttractionInput,
  "id" | "name" | "category" | "latitude" | "longitude" | "source_url" | "attribution"
>;

type Props = {
  hotels: HotelRecommendation[];
  attractions: HotelMapAttraction[];
  selectedHotelId: string | null;
  activeHotelId: string | null;
  mapKey: string;
  onSelectHotel: (id: string) => void;
};

export function HotelLocationMap(props: Props) {
  const [mapModule, setMapModule] = useState<LeafletHotelMapModule | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let active = true;
    import("./LeafletHotelLocationMap")
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

  if (loadFailed) {
    return (
      <div
        className="grid h-[420px] place-items-center rounded-xl border border-border bg-muted/30 p-6 text-center text-sm text-muted-foreground"
        role="status"
      >
        The geographic map could not be loaded. Hotel and attraction details remain available in the
        list.
      </div>
    );
  }

  if (!mapModule) {
    return (
      <div
        className="grid h-[420px] place-items-center rounded-xl border border-border bg-muted/30 text-sm text-muted-foreground"
        role="status"
      >
        Loading geographic map…
      </div>
    );
  }

  return <mapModule.LeafletHotelLocationMap {...props} />;
}
