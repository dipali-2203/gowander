import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { latLngBounds, type LatLngBoundsExpression, type LatLngExpression } from "leaflet";
import "leaflet/dist/leaflet.css";
import { Button } from "@/components/ui/button";
import type { HotelRecommendation } from "@/lib/api";
import type { HotelMapAttraction } from "./HotelLocationMap";

type Props = {
  hotels: HotelRecommendation[];
  attractions: HotelMapAttraction[];
  selectedHotelId: string | null;
  activeHotelId: string | null;
  mapKey: string;
  onSelectHotel: (id: string) => void;
};

const validCoordinates = (latitude: number, longitude: number) =>
  Number.isFinite(latitude) &&
  Number.isFinite(longitude) &&
  latitude >= -90 &&
  latitude <= 90 &&
  longitude >= -180 &&
  longitude <= 180;

function ResetMapView({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap();
  const reset = () => map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
  return (
    <div className="leaflet-top leaflet-right z-[1000]">
      <div className="leaflet-control leaflet-bar border-0 bg-transparent shadow-none">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={reset}
          aria-label="Reset map view"
        >
          Reset map view
        </Button>
      </div>
    </div>
  );
}

function FitRelevantMarkers({
  bounds,
  signature,
}: {
  bounds: LatLngBoundsExpression;
  signature: string;
}) {
  const map = useMap();
  useEffect(() => {
    const timer = window.setTimeout(() => {
      map.invalidateSize();
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [bounds, map, signature]);
  return null;
}

export function LeafletHotelLocationMap({
  hotels,
  attractions,
  selectedHotelId,
  activeHotelId,
  mapKey,
  onSelectHotel,
}: Props) {
  const validHotels = useMemo(
    () => hotels.filter((hotel) => validCoordinates(hotel.latitude, hotel.longitude)),
    [hotels],
  );
  const validAttractions = useMemo(() => {
    const seen = new Set<string>();
    return attractions.filter((attraction) => {
      if (seen.has(attraction.id) || !validCoordinates(attraction.latitude, attraction.longitude)) {
        return false;
      }
      seen.add(attraction.id);
      return true;
    });
  }, [attractions]);
  const coordinates = useMemo(
    () => [
      ...validHotels.map((hotel) => [hotel.latitude, hotel.longitude] as [number, number]),
      ...validAttractions.map(
        (attraction) => [attraction.latitude, attraction.longitude] as [number, number],
      ),
    ],
    [validAttractions, validHotels],
  );
  const signature = `${mapKey}:${coordinates.map(([lat, lon]) => `${lat},${lon}`).join(";")}`;
  const bounds = useMemo(
    () => latLngBounds(coordinates.map(([latitude, longitude]) => [latitude, longitude])),
    [coordinates],
  );
  const center = (coordinates[0] ?? [20.5937, 78.9629]) as LatLngExpression;

  if (coordinates.length === 0) {
    return (
      <div
        className="grid h-[420px] place-items-center rounded-xl border border-border bg-muted/30 p-6 text-center text-sm text-muted-foreground"
        role="status"
      >
        Map location data is unavailable for these hotels and planned attractions.
      </div>
    );
  }

  return (
    <section aria-label="Hotel and planned attraction map" className="space-y-2">
      <div className="relative h-[420px] overflow-hidden rounded-xl border border-border sm:h-[520px]">
        <MapContainer
          key={mapKey}
          center={center}
          zoom={12}
          scrollWheelZoom
          className="h-full w-full"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <FitRelevantMarkers bounds={bounds} signature={signature} />
          <ResetMapView bounds={bounds} />
          {validAttractions.map((attraction) => (
            <CircleMarker
              key={`attraction:${attraction.id}`}
              center={[attraction.latitude, attraction.longitude]}
              radius={7}
              pathOptions={{ color: "#0f766e", fillColor: "#14b8a6", fillOpacity: 0.9, weight: 2 }}
            >
              <Popup>
                <div className="space-y-1 text-sm">
                  <strong>{attraction.name}</strong>
                  <p className="capitalize">{attraction.category}</p>
                  {attraction.source_url ? (
                    <a href={attraction.source_url} target="_blank" rel="noreferrer">
                      Open source record
                    </a>
                  ) : null}
                  {attraction.attribution ? (
                    <p className="text-xs">{attraction.attribution}</p>
                  ) : null}
                </div>
              </Popup>
            </CircleMarker>
          ))}
          {validHotels.map((hotel) => {
            const isSavedSelection = selectedHotelId === hotel.id;
            const isActive = activeHotelId === hotel.id;
            return (
              <CircleMarker
                key={`hotel:${hotel.id}`}
                center={[hotel.latitude, hotel.longitude]}
                radius={isSavedSelection || isActive ? 10 : 8}
                eventHandlers={{ click: () => onSelectHotel(hotel.id) }}
                pathOptions={{
                  color: isSavedSelection ? "#92400e" : "#1e3a8a",
                  fillColor: isSavedSelection ? "#f59e0b" : isActive ? "#2563eb" : "#3b82f6",
                  fillOpacity: 0.95,
                  weight: isSavedSelection || isActive ? 4 : 2,
                }}
              >
                <Popup>
                  <div className="space-y-1 text-sm">
                    <strong>{hotel.name}</strong>
                    <p className="capitalize">{hotel.hotel_type.replaceAll("_", " ")}</p>
                    <p>
                      {hotel.nightly_price === null
                        ? "Price unavailable"
                        : `${hotel.price_currency ?? "Price"} ${hotel.nightly_price.toLocaleString("en-IN")} per room/night`}
                    </p>
                    <p>
                      {hotel.stars === null
                        ? "Mapped classification unavailable; guest ratings unavailable"
                        : `${hotel.stars} mapped stars; guest ratings unavailable`}
                    </p>
                    <p>
                      {hotel.score === null
                        ? "Recommendation score unavailable"
                        : `Recommendation score ${hotel.score}/100`}
                    </p>
                    {hotel.source_url ? (
                      <a href={hotel.source_url} target="_blank" rel="noreferrer">
                        Open OpenStreetMap record
                      </a>
                    ) : null}
                    {hotel.attribution ? <p className="text-xs">{hotel.attribution}</p> : null}
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>
      <div
        className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground"
        aria-label="Map legend"
      >
        <span className="inline-flex items-center gap-1.5">
          <i className="h-2.5 w-2.5 rounded-full bg-blue-500" /> Hotels
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="h-2.5 w-2.5 rounded-full bg-teal-500" /> Planned attractions
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="h-3 w-3 rounded-full border-2 border-amber-800 bg-amber-400" /> Selected
          hotel
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Hotel distances shown in recommendations are straight-line estimates. Map tiles ©
        OpenStreetMap contributors.
      </p>
    </section>
  );
}
