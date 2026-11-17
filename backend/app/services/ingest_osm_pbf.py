"""Bounded city imports from a locally downloaded OSM PBF extract."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import AttractionIngestionJob
from app.services.poi_catalog import (
    DESTINATIONS,
    OSM_ATTRIBUTION,
    OSM_LICENSE,
    normalize_category,
    parse_overpass_response,
    persist_normalized_rows,
)

JOB_PROVIDER_NAME = "geofabrik-pbf"
POI_TAG_VALUES = {
    "tourism": ("attraction", "museum", "artwork", "gallery", "viewpoint", "zoo", "aquarium", "theme_park"),
    "historic": (
        "castle", "monument", "memorial", "ruins", "archaeological_site", "fort", "palace",
        "city_gate", "wayside_shrine", "wayside_cross",
    ),
    "amenity": ("museum", "place_of_worship", "theatre", "arts_centre", "cinema"),
    "leisure": ("park", "garden", "nature_reserve"),
    "natural": ("water", "lake"),
    "building": ("temple",),
}


def _tags(osm_object: Any) -> dict[str, str]:
    return {str(tag.k): str(tag.v) for tag in osm_object.tags}


def _has_attraction_tags(tags: dict[str, str]) -> bool:
    supported = any(tags.get(key) in values for key, values in POI_TAG_VALUES.items())
    return bool((tags.get("name") or tags.get("name:en")) and supported and normalize_category(tags))


def _in_destination_bounds(destination: str, lat: float, lon: float) -> bool:
    south, west, north, east = DESTINATIONS[destination]["bbox"]
    return south <= lat <= north and west <= lon <= east


def _tag_filters(osmium_module: Any) -> list[Any]:
    filter_module = getattr(osmium_module, "filter", None)
    if filter_module is None:
        return []
    tags = [(key, value) for key, values in POI_TAG_VALUES.items() for value in values]
    return [filter_module.TagFilter(*tags)]


def _representative_coordinate(locations: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Use an area centroid for closed rings, otherwise the mean of way vertices."""
    if not locations or any(not (-90 <= lat <= 90 and -180 <= lon <= 180) for lat, lon in locations):
        return None
    if len(locations) >= 4 and locations[0] == locations[-1]:
        ring = [(lon, lat) for lat, lon in locations]
        cross = [
            ring[idx][0] * ring[idx + 1][1] - ring[idx + 1][0] * ring[idx][1]
            for idx in range(len(ring) - 1)
        ]
        area_twice = sum(cross)
        if abs(area_twice) > 1e-12:
            lon = sum(
                (ring[idx][0] + ring[idx + 1][0]) * cross[idx] for idx in range(len(cross))
            ) / (3 * area_twice)
            lat = sum(
                (ring[idx][1] + ring[idx + 1][1]) * cross[idx] for idx in range(len(cross))
            ) / (3 * area_twice)
            return lat, lon
    return sum(point[0] for point in locations) / len(locations), sum(point[1] for point in locations) / len(locations)


def read_pbf_elements(
    pbf_path: str | Path,
    destination: str,
    *,
    osmium_module: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Read named attraction nodes and ways, retaining only city-bounded candidates.

    The first pass records node references for relevant ways. Native filters then
    scan referenced nodes for coordinates and named candidate nodes separately,
    avoiding a full-extract location cache and per-object Python callbacks.
    """
    key = destination.strip().lower()
    if key not in DESTINATIONS:
        raise ValueError("Only Jaipur and Udaipur PBF imports are enabled.")
    path = Path(pbf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PBF extract does not exist: {path}")
    if osmium_module is None:
        try:
            import osmium as osmium_module
        except ImportError as exc:
            raise RuntimeError("PBF import requires Pyosmium. Install backend requirements first.") from exc

    way_records: list[dict[str, Any]] = []
    needed_node_ids: set[int] = set()
    locations: dict[int, tuple[float, float]] = {}
    elements: list[dict[str, Any]] = []
    counts = {
        "nodes_filter_matched": 0, "ways_filter_matched": 0, "relevant_nodes_in_bounds": 0,
        "relevant_ways_in_bounds": 0, "outside_destination_bounds": 0,
        "ways_missing_coordinates": 0,
    }

    class WayReferenceHandler(osmium_module.SimpleHandler):
        def way(self, way):
            counts["ways_filter_matched"] += 1
            tags = _tags(way)
            if not _has_attraction_tags(tags):
                return
            refs = [int(node.ref) for node in way.nodes]
            if not refs:
                counts["ways_missing_coordinates"] += 1
                return
            way_records.append({"type": "way", "id": int(way.id), "tags": tags, "node_refs": refs})
            needed_node_ids.update(refs)

    class NodeCoordinateHandler(osmium_module.SimpleHandler):
        def node(self, node):
            counts["nodes_filter_matched"] += 1
            if not node.location.valid():
                return
            lat, lon = float(node.location.lat), float(node.location.lon)
            locations[int(node.id)] = (lat, lon)

    class NodePoiHandler(osmium_module.SimpleHandler):
        def node(self, node):
            counts["nodes_filter_matched"] += 1
            if not node.location.valid():
                return
            lat, lon = float(node.location.lat), float(node.location.lon)
            node_id = int(node.id)
            tags = _tags(node)
            if not _has_attraction_tags(tags):
                return
            if not _in_destination_bounds(key, lat, lon):
                counts["outside_destination_bounds"] += 1
                return
            elements.append({"type": "node", "id": node_id, "lat": lat, "lon": lon, "tags": tags})
            counts["relevant_nodes_in_bounds"] += 1

    filters = _tag_filters(osmium_module)
    if filters:
        WayReferenceHandler().apply_file(str(path), filters=filters)
        if needed_node_ids:
            id_filter = osmium_module.filter.IdFilter(needed_node_ids)
            NodeCoordinateHandler().apply_file(str(path), filters=[id_filter])
        NodePoiHandler().apply_file(str(path), filters=_tag_filters(osmium_module))
    else:
        WayReferenceHandler().apply_file(str(path))
        if needed_node_ids:
            # Modules used for tests may not expose native filters. Restrict callbacks in Python.
            class AllNodesForNeededWays(osmium_module.SimpleHandler):
                def node(self, node):
                    if int(node.id) in needed_node_ids:
                        NodeCoordinateHandler.node(self, node)

            AllNodesForNeededWays().apply_file(str(path))
        NodePoiHandler().apply_file(str(path))

    for way in way_records:
        refs = way.pop("node_refs")
        if any(ref not in locations for ref in refs):
            counts["ways_missing_coordinates"] += 1
            elements.append(way)  # shared normalizer reports this as invalid
            continue
        point = _representative_coordinate([locations[ref] for ref in refs])
        if point is None:
            counts["ways_missing_coordinates"] += 1
            elements.append(way)
            continue
        lat, lon = point
        if not _in_destination_bounds(key, lat, lon):
            counts["outside_destination_bounds"] += 1
            continue
        way["center"] = {"lat": lat, "lon": lon}
        elements.append(way)
        counts["relevant_ways_in_bounds"] += 1

    counts["elements_in_bounds"] = len(elements) - counts["ways_missing_coordinates"]
    return elements, counts


def ingest_pbf(
    db: Session,
    destination: str,
    pbf_path: str | Path,
    *,
    dry_run: bool = False,
    osmium_module: Any | None = None,
) -> dict[str, Any]:
    key = destination.strip().lower()
    elements, scan_counts = read_pbf_elements(pbf_path, key, osmium_module=osmium_module)
    rows, duplicates, invalid = parse_overpass_response(
        {"elements": elements}, key, max_results=None
    )
    extract_name = Path(pbf_path).name
    dataset = f"Geofabrik Northern Zone PBF: {extract_name}"
    now = datetime.now(timezone.utc)
    persisted = persist_normalized_rows(
        db, rows, destination=key, source_dataset=dataset, dry_run=dry_run
    )
    cli_summary = {name: value for name, value in persisted.items() if name not in {"newly_discovered", "updated_ids"}}
    return {
        "destination": DESTINATIONS[key]["name"], "provider": JOB_PROVIDER_NAME,
        "source_dataset": dataset, "source_file": extract_name, "fetched_at": now.isoformat(),
        "dry_run": dry_run, **scan_counts,
        "records_normalized": len(rows), "duplicates_collapsed": duplicates,
        "invalid_or_unsupported_count": len(invalid), "invalid_ids": invalid[:100],
        **cli_summary, "attribution": OSM_ATTRIBUTION, "license_name": OSM_LICENSE,
        "failed": False,
    }


def run_pbf_ingestion_job(
    db: Session,
    destination: str,
    pbf_path: str | Path,
    *,
    dry_run: bool = False,
    osmium_module: Any | None = None,
) -> dict[str, Any]:
    key = destination.strip().lower()
    if key not in DESTINATIONS:
        raise ValueError("Only Jaipur and Udaipur PBF imports are enabled.")
    if dry_run:
        return ingest_pbf(db, key, pbf_path, dry_run=True, osmium_module=osmium_module)
    job = AttractionIngestionJob(
        destination=DESTINATIONS[key]["name"], provider_name=JOB_PROVIDER_NAME, status="running"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        summary = ingest_pbf(db, key, pbf_path, osmium_module=osmium_module)
        job.status = "succeeded"
        job.completed_at = datetime.now(timezone.utc)
        job.summary = summary
        db.commit()
        return {"job_id": job.id, **summary}
    except Exception as exc:
        db.rollback()
        failed_job = db.get(AttractionIngestionJob, job.id)
        if failed_job is not None:
            failed_job.status = "failed"
            failed_job.completed_at = datetime.now(timezone.utc)
            failed_job.error_message = str(exc)[:500]
            db.commit()
        raise


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    from app import models  # noqa: F401 - register ORM models
    from app.database import Base, SessionLocal, engine, migrate_attraction_catalog_schema
    from sqlalchemy import inspect

    parser = argparse.ArgumentParser(description="Import bounded OSM POIs from a local Geofabrik PBF extract.")
    parser.add_argument("destination", choices=sorted(DESTINATIONS))
    parser.add_argument("pbf_path", type=Path, help="Path to a previously downloaded .osm.pbf extract")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report would-be changes without writing")
    args = parser.parse_args()
    if args.dry_run:
        if "attractions" not in inspect(engine).get_table_names():
            raise RuntimeError("Dry-run requires an existing attraction database table; it will not create or migrate it.")
    else:
        Base.metadata.create_all(bind=engine)
        migrate_attraction_catalog_schema()
    with SessionLocal() as db:
        summary = run_pbf_ingestion_job(db, args.destination, args.pbf_path, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
