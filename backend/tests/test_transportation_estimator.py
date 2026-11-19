from datetime import date

import pytest

from app.models import Trip
from app.services.transportation_estimator import (
    estimate_intercity_transport,
    local_transport_cost,
    manual_cost_record,
    resolve_city,
    validate_manual_amount,
)


def route(monkeypatch, travelers=2, mode="train"):
    monkeypatch.setenv("ROUTING_PROVIDER", "haversine")
    monkeypatch.setenv("TRIP_INTERCITY_ROAD_DISTANCE_FACTOR", "1.25")
    return estimate_intercity_transport(
        origin="Delhi", destination="Jaipur", travelers=travelers, mode=mode,
        origin_latitude=28.6139, origin_longitude=77.209,
        destination_latitude=26.9124, destination_longitude=75.7873,
    )


@pytest.mark.parametrize("mode", ["train", "bus", "flight", "private_car"])
def test_intercity_modes_return_ranges_and_provenance(monkeypatch, mode):
    estimate = route(monkeypatch, travelers=3, mode=mode)["outbound"]
    assert estimate["status"] == "estimated"
    assert estimate["range_min"] <= estimate["amount"] <= estimate["range_max"]
    assert estimate["traveler_count"] == 3
    assert estimate["source"] == "configurable_transport_model"
    assert estimate["estimated_at"]
    assert "not a live fare" in " ".join(estimate["assumptions"]).lower()


def test_passenger_modes_multiply_by_travelers_and_car_is_per_vehicle(monkeypatch):
    one_train = route(monkeypatch, travelers=1, mode="train")["outbound"]
    four_train = route(monkeypatch, travelers=4, mode="train")["outbound"]
    one_car = route(monkeypatch, travelers=1, mode="private_car")["outbound"]
    four_car = route(monkeypatch, travelers=4, mode="private_car")["outbound"]
    assert four_train["amount"] == pytest.approx(one_train["amount"] * 4, abs=0.05)
    assert one_car["unit_basis"] == "per_vehicle"
    assert four_car["amount"] == one_car["amount"]


def test_mode_not_decided_returns_mode_range_not_a_false_selected_mode(monkeypatch):
    estimate = route(monkeypatch, travelers=2, mode=None)
    outbound = estimate["outbound"]
    assert estimate["provisional"] is True
    assert outbound["mode"] is None
    assert set(outbound["mode_estimates"]) == {"train", "bus", "flight", "private_car"}
    assert outbound["range_min"] == min(item["range_min"] for item in outbound["mode_estimates"].values())
    assert outbound["range_max"] == max(item["range_max"] for item in outbound["mode_estimates"].values())
    assert "provisional" in " ".join(outbound["assumptions"]).lower()


def test_outbound_and_return_are_separate_records_with_same_model_assumption(monkeypatch):
    estimate = route(monkeypatch, mode="bus")
    assert estimate["outbound"] is not estimate["return"]
    assert "Outbound leg" in " ".join(estimate["outbound"]["assumptions"])
    assert "Return leg" in " ".join(estimate["return"]["assumptions"])


def test_route_is_unavailable_without_resolved_city_coordinates(monkeypatch):
    monkeypatch.setenv("GEOCODING_PROVIDER", "none")
    assert resolve_city("Unknownville") is None
    result = estimate_intercity_transport("Unknownville", "Jaipur", 2, "train")
    assert result["distance_km"] is None
    assert result["outbound"]["status"] == "unavailable"
    assert "no route distance" in " ".join(result["outbound"]["assumptions"]).lower()


@pytest.mark.parametrize(
    ("mode", "expected_basis"),
    [("walking", "per_vehicle"), ("public_transport", "per_passenger"), ("auto", "per_vehicle"),
     ("private_car", "per_vehicle"), ("rental_vehicle", "per_vehicle"), ("mixed", "per_vehicle")],
)
def test_local_transport_modes_have_explicit_pricing_semantics(mode, expected_basis):
    estimate = local_transport_cost(10, 2, mode, 3)
    assert estimate["status"] == "estimated"
    assert estimate["unit_basis"] == expected_basis
    if mode == "walking":
        assert estimate["amount"] == estimate["range_min"] == estimate["range_max"] == 0
    else:
        assert estimate["amount"] > 0
        assert estimate["range_min"] <= estimate["amount"] <= estimate["range_max"]


def test_local_public_transport_multiplies_passengers_but_car_does_not():
    public_one = local_transport_cost(10, 2, "public_transport", 1)
    public_three = local_transport_cost(10, 2, "public_transport", 3)
    car_one = local_transport_cost(10, 2, "private_car", 1)
    car_three = local_transport_cost(10, 2, "private_car", 3)
    assert public_three["amount"] == public_one["amount"] * 3
    assert car_three["amount"] == car_one["amount"]
    assert "straight-line" in " ".join(car_one["assumptions"])


def test_flight_cannot_fall_back_to_mixed_local_rate():
    result = local_transport_cost(12, 3, "flight", 2)
    assert result["status"] == "unavailable"
    assert result["amount"] is None
    assert "intercity" in " ".join(result["assumptions"])


def test_no_local_stops_adds_no_local_cost_instead_of_a_fabricated_route():
    result = local_transport_cost(0, 0, "auto", 2)
    assert result["amount"] == 0
    assert "No local travel legs" in " ".join(result["assumptions"])


def test_manual_zero_and_unusual_amounts_require_explicit_confirmation(monkeypatch):
    estimate = route(monkeypatch, mode="train")["outbound"]
    assert validate_manual_amount(0, estimate)["confirmation_required"] is True
    assert validate_manual_amount(0, estimate, zero_fare_confirmed=True)["confirmation_required"] is False
    warning = validate_manual_amount(1, estimate)
    assert warning["confirmation_required"] is True
    assert "INR" in warning["warning"]
    assert validate_manual_amount(1, estimate, override_confirmed=True)["confirmation_required"] is False


@pytest.mark.parametrize("amount", [-1, float("nan"), float("inf"), 5_000_001])
def test_invalid_manual_amounts_are_rejected(monkeypatch, amount):
    with pytest.raises(ValueError):
        manual_cost_record(amount, route(monkeypatch)["outbound"], zero_fare_confirmed=True, override_confirmed=True)


def test_manual_override_preserves_user_value_and_whole_group_provenance(monkeypatch):
    estimate = route(monkeypatch)["outbound"]
    manual = manual_cost_record(4321, estimate, override_confirmed=True)
    assert manual["amount"] == 4321
    assert manual["status"] == "user_provided"
    assert manual["unit_basis"] == "per_passenger"
    assert manual["amount_basis"] == "whole_group_total"
    assert manual["source"] == "User input"


def test_manual_outbound_does_not_prevent_automatic_return_estimate(monkeypatch):
    from app.api import trips as trips_api

    estimates = {
        "outbound": {"status": "estimated", "amount": 800, "range_min": 500, "range_max": 1100,
                     "source": "configurable_transport_model", "mode": "train", "assumptions": ["model"]},
        "return": {"status": "estimated", "amount": 900, "range_min": 600, "range_max": 1200,
                   "source": "configurable_transport_model", "mode": "train", "assumptions": ["model"]},
    }
    monkeypatch.setattr(trips_api, "estimate_intercity_transport", lambda **kwargs: {**estimates, "origin": None, "destination": None})
    options, _ = trips_api._prepare_intercity_options({
        "traveler_count": 2,
        "intercity_transportation_mode": "train",
        "intercity_outbound_cost": {"amount": 777, "currency": "INR", "status": "user_provided", "source": "User input"},
        "intercity_return_cost": {"amount": None, "currency": "INR", "status": "unavailable"},
    }, origin="Delhi", destination="Jaipur", origin_latitude=28.6, origin_longitude=77.2,
       destination_latitude=26.9, destination_longitude=75.8)
    assert options["intercity_outbound_cost"]["amount"] == 777
    assert options["intercity_outbound_cost"]["status"] == "user_provided"
    assert options["intercity_return_cost"]["amount"] == 900
    assert options["intercity_return_cost"]["status"] == "estimated"


def test_estimate_preview_serializes_both_legs_and_override_warnings(monkeypatch):
    from app.api import trips as trips_api
    from app.schemas import TransportationEstimateRequest

    response = route(monkeypatch, mode="train")
    monkeypatch.setattr(trips_api, "estimate_intercity_transport", lambda **kwargs: response)
    request = TransportationEstimateRequest(
        origin="Delhi", destination="Jaipur", traveler_count=2, intercity_mode="train",
        outbound_amount=1,
    )
    payload = trips_api.preview_transportation_estimate(request)
    assert payload["outbound"]["range_min"] is not None
    assert payload["return"]["range_max"] is not None
    assert payload["manual_validation"]["outbound"]["confirmation_required"] is True
    assert payload["manual_validation"]["return"]["confirmation_required"] is False


def test_estimated_intercity_range_max_is_reserved_for_optimizer(monkeypatch):
    from app.services.budget import attraction_budget_after_fixed_costs

    monkeypatch.setenv("GEOCODING_PROVIDER", "none")
    values = dict(
        owner_user_id=1, name="test", origin="Delhi", destination="Jaipur",
        start_date=date(2026, 12, 1), end_date=date(2026, 12, 1), budget=200_000,
        available_minutes_per_day=600, start_latitude=26.9, start_longitude=75.8,
        preferences={}, planning_options={
            "traveler_count": 2, "transportation_mode": "walking", "accommodation_category": "standard",
            "miscellaneous_budget": 0,
            "intercity_outbound_cost": {"amount": 5000, "currency": "INR", "status": "estimated", "source": "config", "range_max": 8000},
        },
    )
    trip = Trip(**values)
    without = Trip(**{**values, "planning_options": {**values["planning_options"], "intercity_outbound_cost": None}})
    assert attraction_budget_after_fixed_costs(without) - attraction_budget_after_fixed_costs(trip) == 8000
