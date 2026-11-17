from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.database import Base
from app.models import Attraction, AttractionIngestionJob
from app.schemas import AttractionInput, Preferences
from app.services.planner import generate_greedy_itinerary
from app.services.ingest_osm_pbf import (
    _representative_coordinate, ingest_pbf, read_pbf_elements, run_pbf_ingestion_job,
)


class FakeLocation:
    def __init__(self, lat, lon, valid=True):
        self.lat, self.lon, self._valid = lat, lon, valid

    def valid(self):
        return self._valid


class FakeTag:
    def __init__(self, key, value):
        self.k, self.v = key, value


class FakeNode:
    def __init__(self, node_id, lat, lon, tags=None):
        self.id = node_id
        self.location = FakeLocation(lat, lon)
        self.tags = [FakeTag(k, v) for k, v in (tags or {}).items()]


class FakeWayNode:
    def __init__(self, ref):
        self.ref = ref


class FakeWay:
    def __init__(self, way_id, refs, tags):
        self.id = way_id
        self.nodes = [FakeWayNode(ref) for ref in refs]
        self.tags = [FakeTag(k, v) for k, v in tags.items()]


class FakeFilter:
    def __init__(self, *_args):
        pass


class FakeOsmium:
    nodes = [
        FakeNode(1, 26.9850, 75.8500),
        FakeNode(2, 26.9860, 75.8520),
        FakeNode(3, 26.9855, 75.8510, {"name": "Amber Fort", "tourism": "attraction"}),
        FakeNode(4, 27.50, 75.80, {"name": "Outside", "tourism": "museum"}),
        FakeNode(7, 26.92, 75.82, {"name": "Synthetic Hotel", "tourism": "hotel"}),
        FakeNode(5, 24.58, 73.70, {"name": "City Palace Museum", "tourism": "museum"}),
        FakeNode(6, 24.579, 73.701),
    ]
    ways = [
        FakeWay(100, [1, 2], {"name": "Amber Fort", "historic": "castle", "website": "https://example.org"}),
        FakeWay(101, [999], {"name": "Broken geometry", "tourism": "attraction"}),
        FakeWay(102, [6], {"name": "Udaipur Lake Garden", "leisure": "garden"}),
    ]

    class SimpleHandler:
        def apply_file(self, _path, filters=None):
            if hasattr(self, "way"):
                for way in FakeOsmium.ways:
                    self.way(way)
            if hasattr(self, "node"):
                for node in FakeOsmium.nodes:
                    self.node(node)

    class filter:
        TagFilter = FakeFilter
        IdFilter = FakeFilter


def test_closed_way_uses_polygon_centroid():
    assert _representative_coordinate([
        (0, 0), (0, 2), (2, 2), (2, 0), (0, 0),
    ]) == pytest.approx((1, 1))


def test_pbf_parser_reads_nodes_ways_filters_city_and_reuses_normalizer(tmp_path):
    pbf = tmp_path / "extract.osm.pbf"
    pbf.write_bytes(b"test fixture")

    jaipur, counts = read_pbf_elements(pbf, "jaipur", osmium_module=FakeOsmium)
    assert {item["type"] for item in jaipur} == {"node", "way"}
    assert all(
        26.75 <= item.get("lat", item.get("center", {}).get("lat", 26.75)) <= 27.05
        for item in jaipur if "center" in item or "lat" in item
    )
    assert counts["relevant_nodes_in_bounds"] == 1
    assert counts["relevant_ways_in_bounds"] == 1
    assert counts["outside_destination_bounds"] == 3
    assert counts["ways_missing_coordinates"] == 1
    assert not any(item["tags"].get("name") == "Synthetic Hotel" for item in jaipur)

    udaipur, _ = read_pbf_elements(pbf, "udaipur", osmium_module=FakeOsmium)
    assert any(item["tags"].get("name") == "Udaipur Lake Garden" for item in udaipur)
    assert not any(item["tags"].get("name") == "City Palace Museum" for item in jaipur)


def test_pyosmium_reads_a_real_small_pbf(tmp_path):
    osmium = pytest.importorskip("osmium")
    pbf = tmp_path / "tiny.osm.pbf"
    with osmium.SimpleWriter(str(pbf), overwrite=True) as writer:
        writer.add_node(osmium.osm.mutable.Node(id=1, location=(75.8500, 26.9850)))
        writer.add_node(osmium.osm.mutable.Node(id=2, location=(75.8520, 26.9860)))
        writer.add_node(osmium.osm.mutable.Node(
            id=3, location=(75.8510, 26.9855),
            tags={"name": "Writer Fixture Museum", "tourism": "museum"},
        ))
        writer.add_way(osmium.osm.mutable.Way(
            id=100, nodes=[1, 2],
            tags={"name": "Writer Fixture Garden", "leisure": "garden"},
        ))

    elements, counts = read_pbf_elements(pbf, "jaipur")
    assert {element["type"] for element in elements} == {"node", "way"}
    assert counts["relevant_nodes_in_bounds"] == 1
    assert counts["relevant_ways_in_bounds"] == 1


def test_pbf_dry_run_duplicate_safe_repeat_persistence_and_optimizer_contract(tmp_path):
    pbf = tmp_path / "northern-zone-latest.osm.pbf"
    pbf.write_bytes(b"test fixture")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as db:
            dry = ingest_pbf(db, "jaipur", pbf, dry_run=True, osmium_module=FakeOsmium)
            assert dry["dry_run"] is True
            assert dry["new_count"] == 1, dry  # overlapping node/way collapse to one normalized POI
            assert db.scalar(select(func.count()).select_from(Attraction)) == 0

            imported = ingest_pbf(db, "jaipur", pbf, osmium_module=FakeOsmium)
            assert imported["new_count"] == 1
            assert imported["duplicates_collapsed"] == 1
            assert imported["invalid_or_unsupported_count"] == 1
            saved = db.scalar(select(Attraction))
            assert saved.provider_name == "openstreetmap"
            assert saved.external_provider_id == "way/100"  # way has richer tags than duplicate node
            assert saved.source_dataset == "Geofabrik Northern Zone PBF: northern-zone-latest.osm.pbf"
            assert saved.source_url == "https://www.openstreetmap.org/way/100"
            assert saved.license_name == "ODbL-1.0"
            assert saved.attribution == "© OpenStreetMap contributors"
            assert saved.entrance_fee is None and saved.opening_hours is None
            assert saved.visit_duration_minutes is None

            repeated = ingest_pbf(db, "jaipur", pbf, osmium_module=FakeOsmium)
            assert repeated["new_count"] == 0
            assert repeated["updated_count"] == 1
            assert db.scalar(select(func.count()).select_from(Attraction)) == 1

            # Existing optimizer contract continues to accept the imported row.
            optimizer_input = AttractionInput.model_validate({
                "id": saved.id, "name": saved.name, "category": "history",
                "latitude": saved.latitude, "longitude": saved.longitude,
                "cost": saved.cost, "visit_minutes": saved.visit_minutes,
                "preference_score": saved.preference_score,
            })
            plan = generate_greedy_itinerary(
                attractions=[optimizer_input], preferences=Preferences(),
                start_latitude=26.9124, start_longitude=75.7873,
                budget=1000, available_minutes=1200,
            )
            assert plan["stops"][0].attraction_id == saved.id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_real_pbf_job_is_recorded_with_provider_and_summary(tmp_path):
    pbf = tmp_path / "regional.osm.pbf"
    pbf.write_bytes(b"test fixture")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as db:
            result = run_pbf_ingestion_job(db, "jaipur", pbf, osmium_module=FakeOsmium)
            job = db.get(AttractionIngestionJob, result["job_id"])
            assert job.status == "succeeded"
            assert job.provider_name == "geofabrik-pbf"
            assert job.summary["source_file"] == "regional.osm.pbf"
            assert job.summary["new_count"] == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()

