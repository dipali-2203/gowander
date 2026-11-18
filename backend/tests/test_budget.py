from datetime import date

import pytest

from app.models import Hotel, Trip, TripAccommodation
from app.schemas import AttractionInput, ItineraryStop, MultiDayOptimizeRequest, TripCreate
from app.services.budget import attraction_budget_after_fixed_costs, estimate_trip_budget


def make_trip(**overrides):
    values = {
        "owner_user_id": 1,
        "name": "Test trip",
        "origin": "Delhi",
        "destination": "Jaipur",
        "start_date": date(2026, 12, 1),
        "end_date": date(2026, 12, 3),
        "budget": 20000,
        "available_minutes_per_day": 1200,
        "start_latitude": 26.9124,
        "start_longitude": 75.7873,
        "preferences": {},
        "planning_options": {
            "traveler_count": 2,
            "transportation_mode": "public transport",
            "accommodation_category": "standard",
            "meal_preferences": ["vegetarian"],
            "miscellaneous_budget": 500,
        },
    }
    values.update(overrides)
    return Trip(**values)


def test_fallback_budget_uses_explicit_config_and_reports_categories(monkeypatch):
    monkeypatch.setenv("TRIP_LOCAL_FARE_INR_PER_KM_PUBLIC_TRANSPORT", "10")
    monkeypatch.setenv("TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_STANDARD", "1000")
    monkeypatch.setenv("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", "100")
    trip = make_trip()
    attraction = AttractionInput(
        id="museum", name="Museum", category="history",
        latitude=26.92, longitude=75.82, cost=100, visit_minutes=60,
        preference_score=0.8,
    )
    days = [{
        "total_cost": 100,
        "stops": [ItineraryStop(
            attraction_id="museum", name="Museum", arrival_minute=540,
            departure_minute=600, travel_minutes_before=10, cost=100,
            preference_score=0.8, risk_score=0.0,
        )],
    }]

    estimate = estimate_trip_budget(
        trip=trip, days=days, attractions=[attraction], data_source="synthetic",
    )
    amounts = {category["key"]: category["amount"] for category in estimate["categories"]}

    assert amounts["attractions"] == 100
    assert amounts["accommodation"] == 2000
    assert amounts["meals"] == 600
    assert amounts["miscellaneous"] == 500
    assert amounts["transportation"] > 0
    assert estimate["total_estimated"] == sum(amounts.values())
    assert estimate["per_person"] == pytest.approx(estimate["total_estimated"] / 2, abs=0.01)
    assert estimate["within_budget"] is True
    assert any("legacy destination-only total" in item for item in estimate["exclusions"])


def test_fixed_estimates_are_reserved_before_attraction_budget(monkeypatch):
    monkeypatch.setenv("TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_STANDARD", "1000")
    monkeypatch.setenv("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", "100")
    trip = make_trip()
    assert attraction_budget_after_fixed_costs(trip) == 16900

    constrained = make_trip(budget=2000)
    assert attraction_budget_after_fixed_costs(constrained) == 0


def test_luxury_level_changes_configurable_hotel_and_meal_allowances(monkeypatch):
    monkeypatch.setenv("TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_STANDARD", "1000")
    monkeypatch.setenv("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", "100")
    low = make_trip(planning_options={**make_trip().planning_options, "luxury_level": 1})
    high = make_trip(planning_options={**make_trip().planning_options, "luxury_level": 5})
    def amounts(trip):
        result = estimate_trip_budget(trip=trip, days=[], attractions=[], data_source="osm")
        return {item["key"]: item["amount"] for item in result["categories"]}
    assert amounts(high)["accommodation"] > amounts(low)["accommodation"]
    assert amounts(high)["meals"] > amounts(low)["meals"]


def test_unknown_attraction_fee_is_counted_and_not_reported_as_free_entry():
    trip = make_trip()
    attraction = AttractionInput(
        id="unknown-fee", name="Unknown fee attraction", category="history",
        latitude=26.92, longitude=75.82, cost=0, visit_minutes=60,
        preference_score=0.8, data_source="osm", cost_known=False,
    )
    day = {
        "total_cost": 0,
        "stops": [ItineraryStop(
            attraction_id=attraction.id, name=attraction.name, arrival_minute=540,
            departure_minute=600, travel_minutes_before=0, cost=0,
            preference_score=0.8, risk_score=None,
        )],
    }
    estimate = estimate_trip_budget(
        trip=trip, days=[day], attractions=[attraction], data_source="osm",
    )
    assert estimate["unknown_attraction_fee_count"] == 1
    assert estimate["is_complete"] is False
    assert "zero-cost optimizer placeholder" in " ".join(estimate["exclusions"])


def test_expense_estimate_discloses_outbound_return_and_unquoted_costs():
    estimate = estimate_trip_budget(
        trip=make_trip(), days=[], attractions=[], data_source="osm",
    )
    exclusions = " ".join(estimate["exclusions"])
    assert "outbound and return" in exclusions
    assert "booking prices" in exclusions
    assert "menu prices" in exclusions
    assert "Parking" in exclusions


def test_selected_hotel_sourced_inr_rate_replaces_allowance_without_double_counting(monkeypatch):
    monkeypatch.setenv("TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_STANDARD", "1000")
    hotel = Hotel(
        id="osm:node:1", destination="Jaipur", name="Mapped Hotel", hotel_type="hotel",
        latitude=26.92, longitude=75.82, stars=None, amenities=[], nightly_price=2500,
        price_currency="INR", price_source="OpenStreetMap hotel:price tag",
        provider_name="openstreetmap", external_provider_id="node/1", raw_tags={},
    )
    selected = TripAccommodation(trip_id=1, hotel_id=hotel.id, hotel=hotel)
    trip = make_trip(accommodation_selection=selected)
    estimate = estimate_trip_budget(trip=trip, days=[], attractions=[], data_source="osm")
    accommodation = next(item for item in estimate["categories"] if item["key"] == "accommodation")
    assert accommodation["amount"] == 5000  # 2 nights, 1 room, sourced INR 2,500/room/night
    assert accommodation["source"] == "selected_hotel"
    assert "not a booking quote" in " ".join(estimate["exclusions"])


def test_selected_hotel_without_price_keeps_existing_allowance(monkeypatch):
    monkeypatch.setenv("TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_STANDARD", "1000")
    hotel = Hotel(
        id="osm:node:2", destination="Jaipur", name="Unpriced Hotel", hotel_type="hotel",
        latitude=26.92, longitude=75.82, stars=None, amenities=[], nightly_price=None,
        price_currency=None, price_source=None,
        provider_name="openstreetmap", external_provider_id="node/2", raw_tags={},
    )
    trip = make_trip(accommodation_selection=TripAccommodation(trip_id=1, hotel_id=hotel.id, hotel=hotel))
    estimate = estimate_trip_budget(trip=trip, days=[], attractions=[], data_source="osm")
    accommodation = next(item for item in estimate["categories"] if item["key"] == "accommodation")
    assert accommodation["amount"] == 2000
    assert "no supported INR nightly rate" in " ".join(accommodation["assumptions"])


def test_complete_budget_includes_independent_user_provided_intercity_legs():
    trip = make_trip(planning_options={
        **make_trip().planning_options,
        "intercity_transportation_mode": "train",
        "intercity_outbound_cost": {"amount": 1500, "currency": "INR", "status": "user_provided"},
        "intercity_return_cost": {"amount": 900, "currency": "INR", "status": "user_provided"},
    })
    estimate = estimate_trip_budget(trip=trip, days=[], attractions=[], data_source="osm")
    complete = estimate["complete_budget"]
    categories = {item["key"]: item for item in complete["categories"]}

    assert complete["schema_version"] == 2
    assert categories["intercity_outbound"]["amount"] == 1500
    assert categories["intercity_return"]["amount"] == 900
    assert categories["intercity_outbound"]["status"] == "user_provided"
    assert complete["total_estimate"] == sum(item["amount"] for item in complete["categories"])
    assert complete["completeness"] == "complete"
    # The legacy destination estimate remains compatible and excludes intercity.
    assert estimate["total_estimated"] == sum(item["amount"] for item in estimate["categories"])


def test_estimated_intercity_cost_is_retained_and_reserved():
    trip = make_trip(planning_options={
        **make_trip().planning_options,
        "intercity_outbound_cost": {
            "amount": 1200, "currency": "INR", "status": "estimated",
            "source": "Traveler-supplied estimate", "assumptions": ["Not a fare quote."],
        },
    })
    estimate = estimate_trip_budget(trip=trip, days=[], attractions=[], data_source="osm")
    outbound = next(item for item in estimate["complete_budget"]["categories"] if item["key"] == "intercity_outbound")

    assert outbound["amount"] == 1200
    assert outbound["status"] == "estimated"
    assert outbound["source"] == "Traveler-supplied estimate"
    assert attraction_budget_after_fixed_costs(trip) == 20000 - 11700 - 1200


def test_unavailable_intercity_costs_are_null_and_excluded_from_complete_total():
    estimate = estimate_trip_budget(trip=make_trip(), days=[], attractions=[], data_source="osm")
    complete = estimate["complete_budget"]
    categories = {item["key"]: item for item in complete["categories"]}

    assert categories["intercity_outbound"]["amount"] is None
    assert categories["intercity_return"]["amount"] is None
    assert set(complete["unavailable_categories"]) == {"intercity_outbound", "intercity_return"}
    assert complete["total_estimate"] is None
    assert complete["remaining_budget"] is None


def test_non_inr_intercity_input_is_preserved_but_not_added_without_conversion():
    trip = make_trip(planning_options={
        **make_trip().planning_options,
        "intercity_outbound_cost": {"amount": 100, "currency": "USD", "status": "user_provided"},
    })
    estimate = estimate_trip_budget(trip=trip, days=[], attractions=[], data_source="osm")
    outbound = next(item for item in estimate["complete_budget"]["categories"] if item["key"] == "intercity_outbound")

    assert outbound["amount"] is None
    assert outbound["currency"] == "USD"
    assert outbound["status"] == "unavailable"
    assert "cannot be converted" in " ".join(outbound["assumptions"])


def test_unknown_attraction_fee_is_partial_in_complete_budget():
    trip = make_trip()
    attraction = AttractionInput(
        id="unknown", name="Unknown fee", category="history", latitude=26.92, longitude=75.82,
        cost=0, visit_minutes=60, preference_score=0.8, cost_known=False,
    )
    estimate = estimate_trip_budget(
        trip=trip, attractions=[attraction], data_source="osm",
        days=[{"total_cost": 0, "stops": [{"attraction_id": "unknown"}]}],
    )
    fees = next(item for item in estimate["complete_budget"]["categories"] if item["key"] == "attraction_fees")

    assert fees["status"] == "partial"
    assert fees["amount"] == 0
    assert "attraction_fees" in estimate["complete_budget"]["partial_categories"]
    assert estimate["complete_budget"]["total_estimate"] is None


def test_complete_budget_allocation_clamps_when_reserved_costs_exceed_budget():
    trip = make_trip(
        budget=1000,
        planning_options={
            **make_trip().planning_options,
            "intercity_outbound_cost": {"amount": 2000, "currency": "INR", "status": "user_provided"},
        },
    )
    assert attraction_budget_after_fixed_costs(trip) == 0


def test_trip_create_allows_legacy_missing_origin_location_and_validates_coordinate_pair():
    values = {
        "origin": "Delhi", "destination": "Jaipur", "start_date": "2026-12-01",
        "end_date": "2026-12-02", "budget": 20000, "start_latitude": 26.9,
        "start_longitude": 75.8,
    }
    assert TripCreate(**values).origin_latitude is None
    with pytest.raises(ValueError, match="provided together"):
        TripCreate(**{**values, "origin_latitude": 28.6})


def test_saved_plan_uses_complete_budget_status_when_intercity_causes_overrun(monkeypatch):
    from app.api import trips as trips_api

    trip = make_trip(
        budget=15000,
        planning_options={
            **make_trip().planning_options,
            "traveler_count": 1,
            "transportation_mode": "walking",
            "miscellaneous_budget": 100,
            "intercity_outbound_cost": {"amount": 2000, "currency": "INR", "status": "user_provided"},
            "intercity_return_cost": {"amount": 2000, "currency": "INR", "status": "user_provided"},
        },
    )
    seen_budgets = []

    def generated_plan(**kwargs):
        seen_budgets.append(kwargs["budget"])
        return {
            "days": [{"stops": [], "warnings": [], "total_cost": 2000}],
            "total_cost": 2000,
            "total_travel_minutes": 0,
            "total_visit_minutes": 0,
            "satisfaction": 0,
            "risk_score": None,
            "risk_data_status": "unavailable",
            "feasible": True,
            "warnings": [],
        }

    monkeypatch.setattr(trips_api, "generate_multiday_greedy", generated_plan)
    request = MultiDayOptimizeRequest(
        attractions=[{
            "id": "museum", "name": "Museum", "category": "museum",
            "latitude": 26.92, "longitude": 75.82, "cost": 2000,
            "visit_minutes": 60, "preference_score": 0.8,
        }],
        data_source="osm",
    )
    result = trips_api._build_saved_multiday_plan(trip, request)
    estimate = result["budget_estimate"]

    assert seen_budgets == [1500]
    assert estimate["within_budget"] is True  # legacy destination-only status
    assert estimate["complete_budget"]["total_estimate"] == 15500
    assert estimate["complete_budget"]["within_budget"] is False
    assert result["feasible"] is False
    assert any("complete-trip costs exceed the budget by ₹500" in warning for warning in result["warnings"])
