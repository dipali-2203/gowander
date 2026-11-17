from datetime import date

from app.schemas import AttractionInput, ConfirmedActivity, Preferences
from app.services.itinerary_candidates import deduplicate_itinerary_candidates
from app.services.multiday import generate_multiday_greedy


def poi(
    attraction_id: str,
    name: str,
    *,
    latitude: float = 24.58,
    longitude: float = 73.68,
    category: str = "viewpoint",
    provider_id: str | None = None,
    tags: dict[str, str] | None = None,
    verification_status: str = "provider_retrieved",
) -> AttractionInput:
    return AttractionInput(
        id=attraction_id,
        name=name,
        category=category,
        catalog_category=category,
        latitude=latitude,
        longitude=longitude,
        visit_minutes=45,
        preference_score=0.8,
        data_source="osm",
        provider_name="openstreetmap",
        external_provider_id=provider_id or attraction_id,
        raw_tags=tags or {},
        verification_status=verification_status,
    )


def test_same_osm_identity_collapses_even_if_representations_differ():
    rows, warnings = deduplicate_itinerary_candidates(
        [poi("node", "Old name", provider_id="node/42"), poi("copy", "Other name", provider_id="node/42")]
    )
    assert len(rows) == 1
    assert warnings and "catalog records were preserved" in warnings[0]


def test_identical_ids_with_a_precomputed_matrix_are_filtered_and_matrix_remapped():
    from app.services.planner import generate_greedy_itinerary

    first = poi("same", "Museum")
    second = poi("same", "Museum")
    first.opening_minute = second.opening_minute = 0
    first.closing_minute = second.closing_minute = 120
    result = generate_greedy_itinerary(
        attractions=[first, second], preferences=Preferences(),
        start_latitude=24.58, start_longitude=73.68, budget=100,
        available_minutes=120, travel_matrix=[[0, 0, 0], [0, 0, 1], [0, 1, 0]],
    )
    assert len(result["stops"]) == 1


def test_normalized_spelling_variants_nearby_collapse_and_prefer_verified():
    sparse = poi("sparse", "Sunset Viewpoint", tags={})
    richer = poi(
        "rich", "Sunset View", longitude=73.6802,
        tags={"tourism": "viewpoint", "wikidata": "Q123"},
        verification_status="manually_verified",
    )
    rows, _ = deduplicate_itinerary_candidates([sparse, richer])
    assert [row.id for row in rows] == ["rich"]


def test_node_and_way_for_same_place_are_detected_using_name_and_distance():
    node = poi("node", "Lake Pichola Viewpoint", provider_id="node/1")
    way = poi("way", "Lake Pichola View Point", longitude=73.6801, provider_id="way/2")
    rows, _ = deduplicate_itinerary_candidates([node, way])
    assert len(rows) == 1


def test_similar_name_far_away_is_preserved():
    rows, warnings = deduplicate_itinerary_candidates(
        [poi("a", "Sunset Viewpoint"), poi("b", "Sunset View", latitude=24.61)]
    )
    assert len(rows) == 2
    assert warnings == []


def test_different_attractions_in_same_complex_are_preserved():
    rows, _ = deduplicate_itinerary_candidates(
        [poi("palace", "City Palace", category="museum"), poi("temple", "Jagdish Temple", category="religious")]
    )
    assert {row.id for row in rows} == {"palace", "temple"}


def test_distinct_close_viewpoints_are_preserved():
    rows, _ = deduplicate_itinerary_candidates(
        [poi("sunset", "Sunset Viewpoint"), poi("fateh", "Fateh Sagar Viewpoint", longitude=73.6801)]
    )
    assert len(rows) == 2


def test_duplicate_physical_attraction_is_not_repeated_on_different_days():
    result = generate_multiday_greedy(
        attractions=[
            poi("first", "Sunset Viewpoint"),
            poi("second", "Sunset View", longitude=73.6801),
        ],
        preferences=Preferences(),
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 3),
        start_latitude=24.58,
        start_longitude=73.68,
        budget=1000,
        available_minutes_per_day=1140,
        meal_breaks=[],
        confirmed_activities=[],
        routing_provider="haversine",
    )
    scheduled = [stop.name for day in result["days"] for stop in day["stops"]]
    assert len(scheduled) == 1
    assert any("likely duplicate attraction" in warning for warning in result["warnings"])


def test_duplicate_fixed_reservation_cannot_repeat_on_another_day():
    attraction = poi("fixed", "City Palace", category="historical")
    attraction.opening_minute = 0
    attraction.closing_minute = 1140
    result = generate_multiday_greedy(
        attractions=[attraction], preferences=Preferences(),
        start_date=date(2026, 12, 1), end_date=date(2026, 12, 2),
        start_latitude=24.58, start_longitude=73.68, budget=1000,
        available_minutes_per_day=1140, meal_breaks=[],
        confirmed_activities=[
            ConfirmedActivity(attraction_id="fixed", day_number=1, start_minute=600),
            ConfirmedActivity(attraction_id="fixed", day_number=2, start_minute=600),
        ],
        routing_provider="haversine",
    )
    assert sum(len(day["stops"]) for day in result["days"]) == 1
    assert any(
        "Duplicate confirmed activity" in warning for warning in result["days"][1]["warnings"]
    )
