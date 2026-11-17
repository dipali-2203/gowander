from app.services.attraction_priority import attraction_priority
from app.schemas import AttractionInput, Preferences
from app.services.attraction_relevance import balanced_interest_utility, category_diversity_factor, interest_match, unsupported_interests
from app.services.planner import generate_greedy_itinerary


def test_priority_uses_category_and_explainable_osm_tags_not_popularity():
    featured, reasons = attraction_priority(
        "historical", "Amber Fort", {"historic": "fort", "heritage": "2"}
    )
    generic, generic_reasons = attraction_priority("park", "Sector 4 Park", {})
    assert featured > generic
    assert "heritage or linked reference tag" in reasons
    assert "generic place name" in generic_reasons


def test_priority_category_base_can_be_configured(monkeypatch):
    monkeypatch.setenv("GOWANDER_PRIORITY_PARK", "0.9")
    score, reasons = attraction_priority("park", "Central Park")
    assert score == 0.9
    assert reasons == ["Park category"]


def test_known_udaiapur_landmark_uses_transparent_manual_relevance_anchor():
    score, reasons = attraction_priority("museum", "City Palace", {"tourism": "museum"})
    assert score == 0.99
    assert "manually curated Udaipur landmark" in reasons


def make_poi(id, category, tags=None, priority=0.7):
    return AttractionInput(
        id=id, name=id, category=category, catalog_category=category,
        latitude=24.5, longitude=73.7, visit_minutes=60, preference_score=0.5,
        raw_tags=tags or {}, priority_score=priority,
    )


def test_multiple_interests_balance_spiritual_heritage_and_adventure():
    preferences = Preferences(interests={
        "heritage": 1, "spiritual": 1, "adventure": 1, "mountains": 1, "road trips": 1,
    })
    temple = make_poi("temple", "religious", {"amenity": "place_of_worship"})
    palace = make_poi("palace", "museum", {"tourism": "museum"}, 0.9)
    viewpoint = make_poi("viewpoint", "viewpoint", {"natural": "cliff"})
    assert interest_match(temple, preferences.interests) == 0.2
    assert interest_match(palace, preferences.interests) == 0.18
    assert interest_match(viewpoint, preferences.interests) > interest_match(temple, preferences.interests)
    assert balanced_interest_utility([temple, palace, viewpoint], preferences) > 0
    assert "Road Trips" in unsupported_interests([temple, palace, viewpoint], preferences.interests)


def test_category_diversity_diminishes_repeated_religious_stops():
    first = make_poi("first-temple", "religious")
    second = make_poi("second-temple", "religious")
    counts = {"religious": 1}
    assert category_diversity_factor(second, counts) < category_diversity_factor(first, {})


def test_greedy_selection_includes_relevant_nonreligious_categories():
    attractions = [
        make_poi("temple-a", "religious", {"amenity": "place_of_worship"}, 0.45),
        make_poi("temple-b", "religious", {"amenity": "place_of_worship"}, 0.4),
        make_poi("temple-c", "religious", {"amenity": "place_of_worship"}, 0.4),
        make_poi("palace", "museum", {"tourism": "museum", "historic": "palace"}, 0.95),
        make_poi("hill-view", "viewpoint", {"natural": "cliff", "sport": "hiking"}, 0.9),
    ]
    for item in attractions:
        item.data_source = "osm"
        item.opening_minute = 540
        item.closing_minute = 1140
    preferences = Preferences(
        interests={"heritage": 1, "spiritual": 1, "adventure": 1, "mountains": 1, "road trips": 1},
        travel_pace=0.9,
    )
    result = generate_greedy_itinerary(attractions, preferences, 24.5, 73.7, 10000, 1140, start_minute=540)
    categories = {next(item.catalog_category for item in attractions if item.id == stop.attraction_id) for stop in result["stops"]}
    assert "museum" in categories
    assert "viewpoint" in categories
    assert len(categories) >= 3
