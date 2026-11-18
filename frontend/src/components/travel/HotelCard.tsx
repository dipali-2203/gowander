import { MapPin, Plus, Star } from "lucide-react";
import { motion } from "motion/react";
import type { HotelRecommendation } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function HotelCard({
  hotel,
  onView,
  onAdd,
  adding = false,
}: {
  hotel: HotelRecommendation;
  onView: (hotel: HotelRecommendation) => void;
  onAdd: (hotel: HotelRecommendation) => void;
  adding?: boolean;
}) {
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      className="surface hover-lift space-y-4 p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-semibold">{hotel.name}</h3>
          <p className="mt-1 text-sm capitalize text-muted-foreground">
            {hotel.hotel_type.replaceAll("_", " ")} · {hotel.destination}
          </p>
        </div>
        {hotel.label ? <Badge>{hotel.label}</Badge> : null}
      </div>

      <div className="flex flex-wrap gap-2 text-sm">
        {hotel.nightly_price !== null && hotel.price_currency ? (
          <Badge variant="secondary">
            {hotel.price_currency} {hotel.nightly_price.toLocaleString("en-IN")} / room / night
          </Badge>
        ) : (
          <Badge variant="secondary">Price unavailable</Badge>
        )}
        {hotel.stars !== null ? (
          <Badge variant="secondary" title="Mapped hotel classification, not guest reviews">
            <Star className="mr-1 h-3.5 w-3.5" /> {hotel.stars} mapped stars
          </Badge>
        ) : (
          <Badge variant="secondary">Guest rating unavailable</Badge>
        )}
      </div>

      <p className="flex items-start gap-2 text-sm text-muted-foreground">
        <MapPin className="mt-0.5 h-4 w-4 shrink-0" />
        {hotel.average_distance_km === null
          ? "Distance from itinerary unavailable"
          : `${hotel.average_distance_km.toFixed(1)} km average straight-line distance to planned visits`}
      </p>

      {hotel.amenities.length ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Mapped amenities">
          {hotel.amenities.map((amenity) => (
            <li key={amenity}>
              <Badge variant="outline" className="font-normal">
                {amenity}
              </Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">Amenities unavailable in the source data.</p>
      )}

      {hotel.score !== null ? (
        <p className="text-sm font-medium">
          Match score {hotel.score}/100
          {hotel.score_confidence === "limited" ? " · limited data" : ""}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">
          Not enough itinerary data to score this property.
        </p>
      )}
      {hotel.reasons.length ? (
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {hotel.reasons.slice(0, 2).map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}

      <div className="flex gap-2">
        <Button variant="outline" size="sm" className="flex-1" onClick={() => onView(hotel)}>
          View details
        </Button>
        <Button
          size="sm"
          className="flex-1"
          disabled={hotel.selected || adding}
          onClick={() => onAdd(hotel)}
        >
          <Plus className="h-4 w-4" />
          {hotel.selected ? "Selected" : adding ? "Saving…" : "Add to trip"}
        </Button>
      </div>
      {hotel.source_url ? (
        <p className="text-xs text-muted-foreground">
          Source:{" "}
          <a className="underline" href={hotel.source_url} target="_blank" rel="noreferrer">
            OpenStreetMap
          </a>
          {hotel.source_dataset ? ` · ${hotel.source_dataset}` : ""}
        </p>
      ) : null}
    </motion.article>
  );
}
