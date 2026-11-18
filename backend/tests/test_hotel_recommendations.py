from datetime import date

from app.models import Hotel, Trip
from app.services.hotel_recommendations import planned_attraction_points, ranked_hotels, score_hotel


def make_trip(**changes):
    values = {
        "owner_user_id": 1, "name": "Jaipur visit", "origin": "Delhi", "destination": "Jaipur",
        "start_date": date(2026, 12, 1), "end_date": date(2026, 12, 4), "budget": 40000,
        "available_minutes_per_day": 1100, "start_latitude": 26.9124, "start_longitude": 75.7873,
        "preferences": {}, "planning_options": {
            "traveler_count": 2, "accommodation_category": "standard", "luxury_level": 3,
            "meal_preferences": [],
        },
        "planning_inputs": {"attractions": [
            {"id": "a", "latitude": 26.90, "longitude": 75.78},
            {"id": "b", "latitude": 26.93, "longitude": 75.80},
            {"id": "c", "latitude": 26.93, "longitude": 75.78},
        ]},
        "latest_itinerary": {"days": [{"stops": [
            {"attraction_id": "a"}, {"attraction_id": "b"}, {"attraction_id": "a"},
        ]}]},
    }
    values.update(changes)
    return Trip(**values)


def hotel(hotel_id, lat, lon, **changes):
    values = {
        "id": hotel_id, "destination": "Jaipur", "name": hotel_id, "hotel_type": "hotel",
        "latitude": lat, "longitude": lon, "stars": None, "amenities": [], "raw_tags": {},
        "nightly_price": None, "price_currency": None, "price_source": None,
        "provider_name": "openstreetmap", "external_provider_id": hotel_id,
        "source_dataset": "Geofabrik Northern Zone", "license_name": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors",
    }
    values.update(changes)
    return Hotel(**values)


def test_itinerary_points_use_all_planned_visits_and_preserve_repeat_visits():
    trip = make_trip()
    assert planned_attraction_points(trip) == [
        (26.9, 75.78), (26.93, 75.8), (26.9, 75.78),
    ]


def test_ranking_prefers_hotel_near_the_whole_itinerary_over_one_stop():
    trip = make_trip(latest_itinerary={"days": [{"stops": [
        {"attraction_id": "a"}, {"attraction_id": "b"},
        {"attraction_id": "c"},
    ]}]})
    central = hotel("central", 26.915, 75.79)
    near_only_first = hotel("one-stop", 26.90, 75.78)
    ranked = ranked_hotels([near_only_first, central], trip)
    assert ranked[0]["hotel"].id == "central"
    assert ranked[0]["average_distance_km"] < ranked[1]["average_distance_km"]
    assert ranked[0]["distance_kind"] == "straight_line"
    assert any("average straight-line" in reason for reason in ranked[0]["reasons"])


def test_known_inr_price_quality_and_preference_are_explained_and_deterministic(monkeypatch):
    monkeypatch.setenv("HOTEL_RECOMMENDATION_WEIGHT_PROXIMITY", "0.5")
    property = hotel(
        "priced", 26.915, 75.79, stars=4, nightly_price=3800, price_currency="INR",
        price_source="OSM explicitly mapped price", raw_tags={"breakfast": "yes"},
        amenities=["Breakfast"],
    )
    trip = make_trip(planning_options={
        "traveler_count": 2, "accommodation_category": "premium", "luxury_level": 3,
        "meal_preferences": ["Breakfast"],
    })
    first = score_hotel(property, trip, planned_attraction_points(trip))
    second = score_hotel(property, trip, planned_attraction_points(trip))
    assert first["score"] == second["score"]
    assert first["factor_scores"]["price"] is not None
    assert first["factor_scores"]["quality"] == 80
    assert first["factor_scores"]["preference"] == 100
    assert first["factor_scores"]["amenities"] == 100
    assert any("mapped hotel stars" in reason for reason in first["reasons"])


def test_missing_price_stars_and_coordinates_are_unknown_not_positive_scores():
    trip = make_trip(planning_inputs={"attractions": []}, latest_itinerary={"days": [{"stops": [{"attraction_id": "missing"}]}]})
    record = hotel("unknown", 26.92, 75.81)
    scored = score_hotel(record, trip, planned_attraction_points(trip))
    assert scored["factor_scores"]["proximity"] is None
    assert scored["factor_scores"]["price"] is None
    assert scored["factor_scores"]["quality"] is None
    assert scored["factor_scores"]["amenities"] is None
    assert scored["score"] is None
    assert scored["price_status"] == "unavailable"
    assert scored["rating_status"] == "unavailable"


def test_budget_and_luxury_preferences_use_explicit_type_or_mapped_stars():
    trip_budget = make_trip(planning_options={
        "traveler_count": 1, "accommodation_category": "budget", "luxury_level": 1,
        "meal_preferences": [],
    })
    hostel = hotel("hostel", 26.915, 75.79, hotel_type="hostel")
    luxury = hotel("luxury", 26.915, 75.79, stars=5)
    budget_score = score_hotel(hostel, trip_budget, planned_attraction_points(trip_budget))
    luxury_as_budget = score_hotel(luxury, trip_budget, planned_attraction_points(trip_budget))
    assert budget_score["factor_scores"]["preference"] == 100
    assert luxury_as_budget["factor_scores"]["preference"] == 25

    trip_luxury = make_trip(planning_options={
        "traveler_count": 1, "accommodation_category": "luxury", "luxury_level": 5,
        "meal_preferences": [],
    })
    luxury_score = score_hotel(luxury, trip_luxury, planned_attraction_points(trip_luxury))
    assert luxury_score["factor_scores"]["preference"] == 100


def test_price_above_allowance_scores_worse_than_fitting_price():
    trip = make_trip()
    points = planned_attraction_points(trip)
    within = score_hotel(hotel("within", 26.915, 75.79, nightly_price=3800, price_currency="INR"), trip, points)
    over = score_hotel(hotel("over", 26.915, 75.79, nightly_price=20000, price_currency="INR"), trip, points)
    assert within["factor_scores"]["price"] > over["factor_scores"]["price"]
