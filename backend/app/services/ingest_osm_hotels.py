"""Read and upsert bounded named lodging features from a local OSM PBF extract."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Hotel
from app.services.ingest_osm_pbf import DESTINATIONS, _in_destination_bounds, _representative_coordinate
from app.services.poi_catalog import OSM_ATTRIBUTION, OSM_LICENSE
from app.services.routing import haversine_km


LODGING_TYPES = {
    "hotel", "hostel", "guest_house", "motel", "apartment", "chalet", "resort",
    "alpine_hut", "camp_site", "caravan_site", "inn", "lodge",
}
AMENITY_TAGS = {
    "internet_access": "Wi-Fi", "breakfast": "Breakfast", "parking": "Parking",
    "wheelchair": "Accessible entrance", "air_conditioning": "Air conditioning",
    "elevator": "Elevator", "swimming_pool": "Swimming pool", "restaurant": "Restaurant",
}


def _http_url(value: Any) -> str | None:
    candidate = str(value or "").strip()
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate[:500]


def _hotel_record(tags: dict[str, Any], osm_type: str, osm_id: int, lat: float, lon: float,
                  destination: str, dataset: str, fetched_at: datetime) -> dict[str, Any] | None:
    lodging = str(tags.get("tourism") or "").lower()
    name = str(tags.get("name:en") or tags.get("name") or "").strip()
    if lodging not in LODGING_TYPES or not name:
        return None
    try:
        if not _in_destination_bounds(destination, lat, lon):
            return None
        stars_value = str(tags.get("stars") or tags.get("hotel:stars") or "").strip()
        stars = float(stars_value) if stars_value else None
        if stars is not None and not 0 < stars <= 5:
            stars = None
    except (TypeError, ValueError):
        stars = None

    # OSM lodging prices are rarely standardized. Accept only an explicitly mapped,
    # parseable hotel:price value with an explicit currency tag.
    raw_price = str(tags.get("hotel:price") or "").strip()
    price_match = re.fullmatch(r"\s*(\d+(?:\.\d{1,2})?)\s*", raw_price)
    price_currency = str(tags.get("hotel:price:currency") or "").strip().upper()
    price_unit = str(tags.get("hotel:price:unit") or "").strip().lower().replace("_", "/")
    nightly_price = (
        float(price_match.group(1))
        if price_match and price_currency and price_unit in {"room/night", "per/room/night"}
        else None
    )
    if price_currency and not re.fullmatch(r"[A-Z]{3}", price_currency):
        price_currency = ""
        nightly_price = None

    amenities = [label for key, label in AMENITY_TAGS.items()
                 if str(tags.get(key) or "").lower() in {"yes", "true", "available", "free", "paid"}]
    address_parts = [str(tags.get(key)).strip() for key in
                     ("addr:housenumber", "addr:street", "addr:suburb", "addr:city") if tags.get(key)]
    external_id = f"{osm_type}/{osm_id}"
    return {
        "id": f"osm:{osm_type}:{osm_id}", "destination": DESTINATIONS[destination]["name"],
        "name": name[:200], "hotel_type": lodging, "latitude": lat, "longitude": lon,
        "stars": stars, "amenities": amenities, "address": ", ".join(address_parts)[:300] or None,
        "website": _http_url(tags.get("website") or tags.get("contact:website")),
        "phone": str(tags.get("phone") or tags.get("contact:phone") or "")[:80] or None,
        "brand": str(tags.get("brand") or tags.get("operator") or "")[:150] or None,
        "nightly_price": nightly_price, "price_currency": price_currency or None,
        "price_source": "OpenStreetMap hotel:price tag" if nightly_price is not None else None,
        "provider_name": "openstreetmap", "external_provider_id": external_id,
        "source_url": f"https://www.openstreetmap.org/{external_id}",
        "source_dataset": dataset, "license_name": OSM_LICENSE,
        "attribution": OSM_ATTRIBUTION, "last_fetched_at": fetched_at,
        "raw_tags": {str(k): str(v)[:500] for k, v in tags.items()
                     if isinstance(v, (str, int, float, bool))},
    }


def read_hotel_pbf(pbf_path: str | Path, destination: str, *, osmium_module: Any | None = None
                   ) -> tuple[list[dict[str, Any]], dict[str, int]]:
    key = destination.strip().lower()
    if key not in DESTINATIONS:
        raise ValueError("Only Jaipur and Udaipur hotel extracts are supported.")
    path = Path(pbf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PBF extract does not exist: {path}")
    if osmium_module is None:
        try:
            import osmium as osmium_module
        except ImportError as exc:
            raise RuntimeError("Hotel PBF import requires Pyosmium. Install backend requirements first.") from exc

    dataset = f"Geofabrik Northern Zone PBF: {path.name}"
    records: list[dict[str, Any]] = []
    way_candidates: list[dict[str, Any]] = []
    needed_refs: set[int] = set()
    locations: dict[int, tuple[float, float]] = {}
    stats = {"nodes_seen": 0, "ways_seen": 0, "records_in_bounds": 0,
             "outside_bounds": 0, "invalid_or_unsupported": 0}

    def tags_of(item: Any) -> dict[str, str]:
        return {str(tag.k): str(tag.v) for tag in item.tags}

    def is_lodging(tags: dict[str, str]) -> bool:
        return bool((tags.get("name") or tags.get("name:en"))
                    and tags.get("tourism", "").lower() in LODGING_TYPES)

    class Handler(osmium_module.SimpleHandler):
        def node(self, node):
            stats["nodes_seen"] += 1
            if not node.location.valid():
                return
            lat, lon = float(node.location.lat), float(node.location.lon)
            node_id = int(node.id)
            if node_id in needed_refs:
                locations[node_id] = (lat, lon)
            tags = tags_of(node)
            row = _hotel_record(tags, "node", node_id, lat, lon, key, dataset, fetched_at)
            if row is not None:
                records.append(row)
                stats["records_in_bounds"] += 1
            elif is_lodging(tags):
                stats["outside_bounds"] += 1

        def way(self, way):
            stats["ways_seen"] += 1
            tags = tags_of(way)
            if not is_lodging(tags):
                return
            refs = [int(node.ref) for node in way.nodes]
            if refs:
                way_candidates.append({"id": int(way.id), "tags": tags, "refs": refs})
                needed_refs.update(refs)

    fetched_at = datetime.now(timezone.utc)
    # Two passes allow representative coordinates when ways have no inline locations.
    tag_filter = getattr(getattr(osmium_module, "filter", None), "TagFilter", None)
    filters = [tag_filter(*[("tourism", lodging_type) for lodging_type in sorted(LODGING_TYPES)])] if tag_filter else None
    Handler().apply_file(str(path), filters=filters)
    if needed_refs:
        class CoordinateHandler(osmium_module.SimpleHandler):
            def node(self, node):
                node_id = int(node.id)
                if node_id in needed_refs and node.location.valid():
                    locations[node_id] = (float(node.location.lat), float(node.location.lon))
        id_filter = getattr(getattr(osmium_module, "filter", None), "IdFilter", None)
        filters = [id_filter(needed_refs)] if id_filter else None
        CoordinateHandler().apply_file(str(path), filters=filters)
    for way in way_candidates:
        points = [locations[ref] for ref in way["refs"] if ref in locations]
        if len(points) != len(way["refs"]):
            stats["invalid_or_unsupported"] += 1
            continue
        point = _representative_coordinate(points)
        if point is None:
            stats["invalid_or_unsupported"] += 1
            continue
        row = _hotel_record(way["tags"], "way", way["id"], point[0], point[1], key,
                            dataset, fetched_at)
        if row is None:
            stats["outside_bounds"] += 1
        else:
            records.append(row)
            stats["records_in_bounds"] += 1
    def normalized_name(value: str) -> str:
        folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
        return re.sub(r"[^a-z0-9]+", " ", folded).strip()

    deduplicated: list[dict[str, Any]] = []
    for row in sorted(records, key=lambda item: (-len(item["raw_tags"]), item["external_provider_id"])):
        duplicate = any(
            normalized_name(row["name"]) == normalized_name(existing["name"])
            and haversine_km((row["latitude"], row["longitude"]),
                             (existing["latitude"], existing["longitude"])) <= 0.075
            for existing in deduplicated
        )
        if not duplicate:
            deduplicated.append(row)
        else:
            stats["duplicates_collapsed"] = stats.get("duplicates_collapsed", 0) + 1
    return deduplicated, stats


def import_hotel_pbf(db: Session, destination: str, pbf_path: str | Path, *, dry_run: bool = False,
                     osmium_module: Any | None = None) -> dict[str, Any]:
    key = destination.strip().lower()
    dataset = f"Geofabrik Northern Zone PBF: {Path(pbf_path).name}"
    rows, scan = read_hotel_pbf(pbf_path, key, osmium_module=osmium_module)
    added = updated = 0
    for row in rows:
        existing = db.scalar(select(Hotel).where(
            Hotel.provider_name == row["provider_name"],
            Hotel.external_provider_id == row["external_provider_id"],
        ))
        if existing is None:
            added += 1
            if not dry_run:
                db.add(Hotel(**row))
        else:
            updated += 1
            if not dry_run:
                for key_name, value in row.items():
                    setattr(existing, key_name, value)
    if not dry_run:
        db.commit()
    return {
        "destination": DESTINATIONS[key]["name"], "provider": "openstreetmap",
        "source_dataset": dataset,
        "dry_run": dry_run, **scan, "new_count": added, "updated_count": updated,
        "attribution": OSM_ATTRIBUTION, "license_name": OSM_LICENSE,
    }


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    from app import models  # noqa: F401
    from app.database import Base, SessionLocal, engine
    from sqlalchemy import inspect
    parser = argparse.ArgumentParser(description="Import bounded OpenStreetMap lodging from a local PBF extract.")
    parser.add_argument("destination", choices=sorted(DESTINATIONS))
    parser.add_argument("pbf_path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run and "hotels" not in inspect(engine).get_table_names():
        raise RuntimeError("Dry-run requires an existing hotel catalog table; it will not create schema or migrate the database.")
    if not args.dry_run:
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        print(json.dumps(import_hotel_pbf(db, args.destination, args.pbf_path, dry_run=args.dry_run),
                         indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
