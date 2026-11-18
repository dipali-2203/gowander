from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.database import Base
from app.models import Hotel
from app.services.ingest_osm_hotels import import_hotel_pbf, read_hotel_pbf


class FakeLocation:
    def __init__(self, lat, lon):
        self.lat, self.lon = lat, lon

    def valid(self):
        return True


class FakeTag:
    def __init__(self, key, value):
        self.k, self.v = key, value


class FakeNode:
    def __init__(self, node_id, lat, lon, tags=None):
        self.id = node_id
        self.location = FakeLocation(lat, lon)
        self.tags = [FakeTag(key, value) for key, value in (tags or {}).items()]


class FakeWayNode:
    def __init__(self, ref):
        self.ref = ref


class FakeWay:
    def __init__(self, way_id, refs, tags):
        self.id = way_id
        self.nodes = [FakeWayNode(ref) for ref in refs]
        self.tags = [FakeTag(key, value) for key, value in tags.items()]


class FakeFilter:
    def __init__(self, *_args):
        pass


class FakeOsmium:
    nodes = [
        FakeNode(1, 26.9000, 75.7900, {"name": "Amber Guest House", "tourism": "guest_house"}),
        FakeNode(2, 26.9000, 75.7902),
        FakeNode(3, 26.9000, 75.7904),
        FakeNode(4, 26.9200, 75.8200, {"name": "Jaipur Hostel", "tourism": "hostel", "stars": "2", "internet_access": "yes"}),
        FakeNode(5, 27.50, 75.80, {"name": "Outside Lodge", "tourism": "hotel"}),
        FakeNode(6, 24.58, 73.70, {"name": "Udaipur Stay", "tourism": "hotel"}),
    ]
    ways = [
        FakeWay(100, [2, 3], {"name": "Amber Guest House", "tourism": "guest_house", "website": "https://example.org"}),
    ]

    class SimpleHandler:
        def apply_file(self, _path, filters=None):
            if hasattr(self, "node"):
                for node in FakeOsmium.nodes:
                    self.node(node)
            if hasattr(self, "way"):
                for way in FakeOsmium.ways:
                    self.way(way)

    class filter:
        TagFilter = FakeFilter
        IdFilter = FakeFilter


def test_hotel_pbf_reads_named_lodging_nodes_ways_and_city_bounds(tmp_path):
    pbf = tmp_path / "northern-zone.osm.pbf"
    pbf.write_bytes(b"fixture")
    jaipur, stats = read_hotel_pbf(pbf, "jaipur", osmium_module=FakeOsmium)
    assert len(jaipur) == 2  # node/way duplicate collapses; separate hostel remains
    assert stats["duplicates_collapsed"] == 1
    assert {record["hotel_type"] for record in jaipur} == {"guest_house", "hostel"}
    assert all(26.75 <= item["latitude"] <= 27.05 and 75.68 <= item["longitude"] <= 76.0 for item in jaipur)
    guesthouse = next(item for item in jaipur if item["hotel_type"] == "guest_house")
    assert guesthouse["website"] == "https://example.org"
    assert guesthouse["nightly_price"] is None  # no standardized price supplied
    assert guesthouse["attribution"] == "© OpenStreetMap contributors"
    udaipur, _ = read_hotel_pbf(pbf, "udaipur", osmium_module=FakeOsmium)
    assert [item["name"] for item in udaipur] == ["Udaipur Stay"]


def test_pyosmium_reads_real_small_lodging_node_and_way(tmp_path):
    osmium = pytest.importorskip("osmium")
    pbf = tmp_path / "small-lodging.osm.pbf"
    with osmium.SimpleWriter(str(pbf), overwrite=True) as writer:
        writer.add_node(osmium.osm.mutable.Node(id=1, location=(75.8500, 26.9850)))
        writer.add_node(osmium.osm.mutable.Node(id=2, location=(75.8520, 26.9860)))
        writer.add_node(osmium.osm.mutable.Node(
            id=3, location=(75.8510, 26.9855),
            tags={"name": "Real PBF Hotel Node", "tourism": "hotel", "stars": "3"},
        ))
        writer.add_way(osmium.osm.mutable.Way(
            id=100, nodes=[1, 2],
            tags={"name": "Real PBF Guesthouse", "tourism": "guest_house"},
        ))

    rows, stats = read_hotel_pbf(pbf, "jaipur")
    assert {item["name"] for item in rows} == {"Real PBF Hotel Node", "Real PBF Guesthouse"}
    assert stats["records_in_bounds"] == 2
    node = next(item for item in rows if item["name"] == "Real PBF Hotel Node")
    assert node["stars"] == 3
    assert node["external_provider_id"] == "node/3"


def test_hotel_import_is_dry_run_and_repeat_safe_with_source_metadata(tmp_path):
    pbf = tmp_path / "extract.osm.pbf"
    pbf.write_bytes(b"fixture")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as db:
            dry = import_hotel_pbf(db, "jaipur", pbf, dry_run=True, osmium_module=FakeOsmium)
            assert dry["new_count"] == 2
            assert db.scalar(select(func.count()).select_from(Hotel)) == 0
            first = import_hotel_pbf(db, "jaipur", pbf, osmium_module=FakeOsmium)
            assert first["new_count"] == 2
            saved = db.scalar(select(Hotel).where(Hotel.hotel_type == "hostel"))
            assert saved.provider_name == "openstreetmap"
            assert saved.source_url == "https://www.openstreetmap.org/node/4"
            assert saved.source_dataset == "Geofabrik Northern Zone PBF: extract.osm.pbf"
            assert saved.license_name == "ODbL-1.0"
            assert saved.stars == 2
            assert saved.amenities == ["Wi-Fi"]
            repeated = import_hotel_pbf(db, "jaipur", pbf, osmium_module=FakeOsmium)
            assert repeated["new_count"] == 0
            assert repeated["updated_count"] == 2
            assert db.scalar(select(func.count()).select_from(Hotel)) == 2
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
