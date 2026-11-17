from datetime import date

import pytest

from app.models import Trip
from app.schemas import AttractionInput, ItineraryStop
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
    assert any("Intercity travel" in item for item in estimate["exclusions"])


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
