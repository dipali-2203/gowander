import { useEffect, useMemo, useRef, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import type { CircleMarker as LeafletCircleMarker, LatLngBoundsExpression } from "leaflet";
import "leaflet/dist/leaflet.css";
import { Button } from "@/components/ui/button";
import type { AttractionInput } from "@/lib/api";

const cityCenters: Record<string, [number, number]> = {
  jaipur: [26.9124, 75.7873],
  udaipur: [24.5854, 73.7125],
};

const colors = {
  park: "#16a34a",
  religious: "#d97706",
  viewpoint: "#0284c7",
  cultural: "#7c3aed",
  historical: "#b45309",
  museum: "#db2777",
  entertainment: "#e11d48",
  other: "#475569",
} as const;

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

const validCoordinate = (place: AttractionInput) =>
  Number.isFinite(place.latitude) &&
  Number.isFinite(place.longitude) &&
  place.latitude >= -90 &&
  place.latitude <= 90 &&
  place.longitude >= -180 &&
  place.longitude <= 180;

function MapViewport({
  bounds,
  selected,
  markers,
}: {
  bounds: LatLngBoundsExpression | null;
  selected: AttractionInput | null;
  markers: React.MutableRefObject<Record<string, LeafletCircleMarker | null>>;
}) {
  const map = useMap();
  useEffect(() => {
    const timer = window.setTimeout(() => {
      map.invalidateSize();
      if (bounds) map.fitBounds(bounds, { padding: [28, 28], maxZoom: 14 });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [bounds, map]);
  useEffect(() => {
    if (!selected) return;
    map.flyTo([selected.latitude, selected.longitude], Math.max(map.getZoom(), 15), {
      duration: 0.45,
    });
    markers.current[selected.id]?.openPopup();
  }, [map, markers, selected]);
  return null;
}

function ResetMapButton({ bounds }: { bounds: LatLngBoundsExpression | null }) {
  const map = useMap();
  return (
    <button
      type="button"
      className="absolute right-3 top-3 z-[1000] rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-800 shadow"
      onClick={() => {
        if (bounds) map.fitBounds(bounds, { padding: [28, 28], maxZoom: 14 });
      }}
    >
      Reset map view
    </button>
  );
}

function MapLegend() {
  const items = [
    ["Park", colors["park"]],
    ["Religious", colors["religious"]],
    ["Viewpoint", colors["viewpoint"]],
    ["Cultural", colors["cultural"]],
    ["Historical", colors["historical"]],
    ["Museum", colors["museum"]],
    ["Entertainment", colors["entertainment"]],
    ["Other", colors["other"]],
  ] as const;
  return (
    <div className="absolute bottom-3 left-3 z-[1000] flex max-w-[calc(100%-1.5rem)] flex-wrap gap-x-3 gap-y-1 rounded-md border border-slate-300 bg-white/95 p-2 text-[10px] text-slate-800 shadow">
      {items.map(([label, color]) => (
        <span key={label} className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
          {label}
        </span>
      ))}
    </div>
  );
}

export function LeafletAttractionMap({
  city,
  attractions,
  selectedId,
  bookmarkedIds,
  bookmarkBusyId,
  dataset,
  attribution,
  onSelect,
  onBookmark,
}: Props) {
  const [tilesUnavailable, setTilesUnavailable] = useState(false);
  const located = useMemo(() => attractions.filter(validCoordinate), [attractions]);
  const markers = useRef<Record<string, LeafletCircleMarker | null>>({});
  const selected = located.find((place) => place.id === selectedId) ?? null;
  const bounds = useMemo<LatLngBoundsExpression | null>(
    () => (located.length ? located.map((place) => [place.latitude, place.longitude]) : null),
    [located],
  );
  const center: [number, number] = cityCenters[city.toLowerCase()] ?? [26.9124, 75.7873];

  if (!located.length) {
    return (
      <div
        className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground"
        role="status"
      >
        No attractions with valid coordinates match these filters. Catalog records remain available
        in the list.
      </div>
    );
  }

  return (
    <MapContainer
      center={center}
      zoom={12}
      {...(bounds ? { bounds } : {})}
      scrollWheelZoom
      className="z-0 h-full w-full"
      aria-label={`${city} OpenStreetMap attraction map`}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
        eventHandlers={{
          tileerror: () => setTilesUnavailable(true),
          tileload: () => setTilesUnavailable(false),
        }}
      />
      <MapViewport bounds={bounds} selected={selected} markers={markers} />
      <ResetMapButton bounds={bounds} />
      <MapLegend />
      {tilesUnavailable ? (
        <div
          className="absolute right-3 top-14 z-[1000] rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow"
          role="status"
        >
          Map tiles are temporarily unavailable; attraction markers are still shown.
        </div>
      ) : null}
      {located.map((place) => {
        const isSelected = place.id === selectedId;
        const category = (place.catalog_category ?? place.category).toLowerCase();
        const color = colors[category as keyof typeof colors] ?? colors["other"];
        return (
          <CircleMarker
            key={place.id}
            ref={(marker) => {
              markers.current[place.id] = marker;
            }}
            center={[place.latitude, place.longitude]}
            radius={isSelected ? 10 : 7}
            pathOptions={{
              color: isSelected ? "#111827" : color,
              fillColor: color,
              fillOpacity: isSelected ? 1 : 0.82,
              weight: isSelected ? 3 : 2,
            }}
            eventHandlers={{ click: () => onSelect(place.id) }}
          >
            <Popup>
              <div className="min-w-52 space-y-2 text-sm">
                <div>
                  <h3 className="font-semibold">{place.name}</h3>
                  <p className="capitalize text-slate-600">
                    {place.catalog_category ?? place.category}
                  </p>
                </div>
                <p>
                  Entry fee:{" "}
                  {place.cost_known ? `₹${place.cost.toLocaleString("en-IN")}` : "Unknown"}
                </p>
                <p>
                  Visit duration:{" "}
                  {place.visit_duration_known ? `${place.visit_minutes} min` : "Unknown"}
                </p>
                <p>
                  Opening hours:{" "}
                  {place.opening_window_known ? (place.opening_hours ?? "Not provided") : "Unknown"}
                </p>
                <p className="text-xs text-slate-600">
                  Dataset: {place.source_dataset ?? dataset ?? "Source unknown"}
                </p>
                {place.source_url ? (
                  <a
                    href={place.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-700 underline"
                  >
                    Open OSM source record
                  </a>
                ) : null}
                {attribution ? <p className="text-xs text-slate-600">{attribution}</p> : null}
                <Button
                  size="sm"
                  variant={bookmarkedIds.includes(place.id) ? "secondary" : "outline"}
                  disabled={bookmarkBusyId === place.id}
                  onClick={() => onBookmark(place.id, place.name)}
                >
                  {bookmarkedIds.includes(place.id) ? "Remove bookmark" : "Bookmark attraction"}
                </Button>
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
