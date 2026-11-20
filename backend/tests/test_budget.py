from datetime import date
import json

import pytest

from app.models import Hotel, Trip, TripAccommodation
from app.schemas import AttractionInput, ItineraryStop, MultiDayOptimizeRequest, TripCreate
from app.services.budget import (
    attraction_budget_after_fixed_costs,
    estimate_saved_itinerary_budget,
    estimate_trip_budget,
)


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


def test_saved_itinerary_budget_refresh_is_read_only():
    attraction = AttractionInput(
        id="saved-museum", name="Saved Museum", category="history",
        latitude=26.92, longitude=75.82, cost=500, cost_known=True,
        fee_status="verified", fee_currency="INR", fee_pricing_basis="per_person",
        visit_minutes=60, preference_score=0.8,
    )
    stored_itinerary = {
        "days": [{
            "day_number": 1,
            "date": "2026-12-01",
            "stops": [{"attraction_id": "saved-museum", "name": "Saved Museum"}],
        }],
        "budget_estimate": {"complete_budget": None},
    }
    trip = make_trip(
        latest_itinerary=stored_itinerary,
        planning_inputs={"attractions": [attraction.model_dump(mode="json")], "data_source": "catalog"},
        itinerary_stale=False,
    )

    refreshed = estimate_saved_itinerary_budget(trip)

    assert refreshed is not stored_itinerary
    assert refreshed["budget_estimate"]["attraction_fee_details"][0]["status"] == "verified"
    assert refreshed["budget_estimate"]["daily_attraction_fees"][0]["verified_fee_total"] == 1000
    assert trip.latest_itinerary is stored_itinerary
    assert trip.latest_itinerary["budget_estimate"] == {"complete_budget": None}


def test_saved_itinerary_budget_keeps_stale_snapshot():
    stored_itinerary = {"days": [], "budget_estimate": {"complete_budget": None}}
    trip = make_trip(
        latest_itinerary=stored_itinerary,
        planning_inputs={"attractions": []},
        itinerary_stale=True,
    )

    assert estimate_saved_itinerary_budget(trip) is stored_itinerary


def test_fixed_estimates_are_reserved_before_attraction_budget(monkeypatch):
    monkeypatch.setenv("TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_STANDARD", "1000")
    monkeypatch.setenv("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", "100")
    trip = make_trip()
    assert attraction_budget_after_fixed_costs(trip) == 16900

    constrained = make_trip(budget=2000)
    assert attraction_budget_after_fixed_costs(constrained) == 0


def test_food_allowance_is_independent_of_accommodation_tier(monkeypatch):
    monkeypatch.setenv("TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_STANDARD", "1000")
    monkeypatch.setenv("TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY", "100")
    low = make_trip(planning_options={**make_trip().planning_options, "luxury_level": 1})
    high = make_trip(planning_options={**make_trip().planning_options, "luxury_level": 5})
    def amounts(trip):
        result = estimate_trip_budget(trip=trip, days=[], attractions=[], data_source="osm")
        return {item["key"]: item["amount"] for item in result["categories"]}
    assert amounts(high)["accommodation"] > amounts(low)["accommodation"]
    assert amounts(high)["meals"] == amounts(low)["meals"] == 600


def test_unknown_attraction_fee_is_counted_and_not_reported_as_free_entry():
    trip = make_trip()
    attraction = AttractionInput(
        id="unknown-fee", name="Unknown fee attraction", category="history",
        latitude=26.92, longitude=75.82, cost=0, visit_minutes=60,
        preference_score=0.8, data_source="osm", cost_known=False, raw_tags={"fee": "yes"},
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
    assert estimate["is_complete"] is True  # fee=yes permits a configured category estimate
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
        cost=0, visit_minutes=60, preference_score=0.8, cost_known=False, raw_tags={"fee": "yes"},
    )
    estimate = estimate_trip_budget(
        trip=trip, attractions=[attraction], data_source="osm",
        days=[{"total_cost": 0, "stops": [{"attraction_id": "unknown"}]}],
    )
    fees = next(item for item in estimate["complete_budget"]["categories"] if item["key"] == "attraction_fees")

    assert fees["status"] == "estimated"
    assert fees["amount"] == 300  # versioned historical-category estimate, two travelers
    assert fees["estimated_amount"] == 300
    assert fees["unresolved_count"] == 0
    assert fees["estimate_config_version"] == "1.2.0"
    assert "unverified category-level" in " ".join(fees["assumptions"]).lower()
    json.dumps(estimate["complete_budget"])
    assert "attraction_fees" not in estimate["complete_budget"]["partial_categories"]
    assert estimate["complete_budget"]["total_estimate"] is None


def test_verified_attraction_fee_requires_currency_and_basis_and_allows_zero():
    trip = make_trip(planning_options={
        **make_trip().planning_options,
        "traveler_count": 3,
        "intercity_outbound_cost": {"amount": 0, "currency": "INR", "status": "user_provided"},
        "intercity_return_cost": {"amount": 0, "currency": "INR", "status": "user_provided"},
    })
    zero = AttractionInput(
        id="zero", name="Free entry", category="history", latitude=26.92, longitude=75.82,
        cost=0, visit_minutes=60, preference_score=0.8, cost_known=True,
        fee_status="verified", fee_currency="INR", fee_pricing_basis="per_person",
    )
    trip_days = [{"stops": [{"attraction_id": "zero"}, {"attraction_id": "zero"}]}]
    result = estimate_trip_budget(trip=trip, days=trip_days, attractions=[zero], data_source="osm")
    fees = next(item for item in result["complete_budget"]["categories"] if item["key"] == "attraction_fees")
    assert fees["status"] == "verified"
    assert fees["amount"] == 0
    assert fees["verified_count"] == 1
    assert fees["unresolved_count"] == 0


def test_osm_fee_no_is_zero_estimate_with_source_provenance_and_version():
    item = AttractionInput(
        id="free-garden", name="Public Garden", category="park", latitude=26.92, longitude=75.82,
        cost=0, visit_minutes=60, preference_score=0.5, cost_known=False,
        raw_tags={"fee": "no"},
    )
    estimate = estimate_trip_budget(
        trip=make_trip(), attractions=[item], data_source="osm",
        days=[{"stops": [{"attraction_id": item.id}]}],
    )
    fee = estimate["attraction_fee_details"][0]
    assert fee["status"] == "estimated"
    assert fee["estimate_type"] == "source_tag"
    assert fee["source"] == "osm_fee_tag"
    assert fee["estimate_version"] == "1.2.0"
    assert (fee["lower"], fee["representative"], fee["upper"]) == (0, 0, 0)
    assert "not independently verified" in " ".join(fee["assumptions"])


@pytest.mark.parametrize("category", ["park", "viewpoint", "religious", "cultural", "other"])
def test_category_fallback_does_not_price_non_admission_categories(category):
    item = AttractionInput(
        id=f"paid-tag-{category}", name="Public place", category=category,
        latitude=26.92, longitude=75.82, cost=0, visit_minutes=60,
        preference_score=0.5, cost_known=False, raw_tags={"fee": "yes"},
    )
    estimate = estimate_trip_budget(
        trip=make_trip(), attractions=[item], data_source="osm",
        days=[{"stops": [{"attraction_id": item.id}]}],
    )
    assert estimate["attraction_fee_details"][0]["status"] == "unavailable"


@pytest.mark.parametrize("category", ["historical", "museum", "entertainment"])
def test_paid_admission_category_without_fee_tag_remains_unknown(category):
    item = AttractionInput(
        id=f"uncertain-{category}", name="Uncertain admission", category=category,
        latitude=26.92, longitude=75.82, cost=0, visit_minutes=60,
        preference_score=0.5, cost_known=False,
    )
    estimate = estimate_trip_budget(
        trip=make_trip(), attractions=[item], data_source="osm",
        days=[{"stops": [{"attraction_id": item.id}]}],
    )
    assert estimate["attraction_fee_details"][0]["status"] == "unavailable"


def test_explicit_attraction_estimate_precedes_category_fallback(monkeypatch):
    from app.services import budget as budget_service

    monkeypatch.setattr(budget_service, "_budget_estimates", lambda: {
        "version": "test-1", "currency": "INR", "attraction_fee_pricing_basis": "per_person",
        "category_estimates_require_fee_yes": True, "paid_admission_categories": ["museum"],
        "attraction_fee_category_estimates": {
            "museum": {"lower": 10, "representative": 20, "upper": 30},
        },
        "attraction_specific_estimates": {
            "specific": {"lower": 40, "representative": 50, "upper": 60,
                         "currency": "INR", "pricing_basis": "group"},
        },
        "miscellaneous_contingency_percentages": {"lower": 5, "representative": 10, "upper": 15},
    })
    item = AttractionInput(
        id="specific", name="Museum", category="museum", latitude=26.92, longitude=75.82,
        cost=0, visit_minutes=60, preference_score=0.5, cost_known=False,
    )
    result = estimate_trip_budget(
        trip=make_trip(), attractions=[item], data_source="osm",
        days=[{"stops": [{"attraction_id": item.id}]}],
    )
    fee = result["attraction_fee_details"][0]
    assert fee["estimate_type"] == "attraction_specific"
    assert (fee["lower"], fee["representative"], fee["upper"]) == (40, 50, 60)


def test_verified_per_person_and_group_fee_bases_scale_correctly():
    trip = make_trip(planning_options={
        **make_trip().planning_options, "traveler_count": 3,
        "intercity_outbound_cost": {"amount": 0, "currency": "INR", "status": "user_provided"},
        "intercity_return_cost": {"amount": 0, "currency": "INR", "status": "user_provided"},
    })
    attractions = [
        AttractionInput(id="person", name="Per person", category="history", latitude=26.92,
            longitude=75.82, cost=100, visit_minutes=60, preference_score=0.8,
            cost_known=True, fee_status="verified", fee_currency="INR", fee_pricing_basis="per_person"),
        AttractionInput(id="group", name="Group", category="history", latitude=26.92,
            longitude=75.82, cost=250, visit_minutes=60, preference_score=0.8,
            cost_known=True, fee_status="verified", fee_currency="INR", fee_pricing_basis="group"),
    ]
    result = estimate_trip_budget(trip=trip, days=[{"stops": [
        {"attraction_id": "person"}, {"attraction_id": "group"},
    ]}], attractions=attractions, data_source="osm")
    fees = next(item for item in result["complete_budget"]["categories"] if item["key"] == "attraction_fees")
    assert fees["amount"] == 550


def test_unknown_category_remains_unresolved_without_zeroing_or_fake_fee():
    trip = make_trip()
    item = AttractionInput(id="unknown-category", name="Unpriced", category="sightseeing",
        catalog_category="other",
        latitude=26.92, longitude=75.82, cost=0, visit_minutes=60, preference_score=0.8,
        cost_known=None)
    result = estimate_trip_budget(trip=trip,
        days=[{"stops": [{"attraction_id": item.id}]}], attractions=[item], data_source="osm")
    fees = next(item for item in result["complete_budget"]["categories"] if item["key"] == "attraction_fees")
    assert fees["status"] == "partial"
    assert fees["amount"] is None
    assert fees["unresolved_count"] == 1
    assert result["unknown_attraction_fee_count"] == 1


def test_historic_osm_tags_resolve_other_category_with_historical_estimate():
    trip = make_trip()
    item = AttractionInput(
        id="osm:way:monsoon-palace", name="Sajjan Garh - Monsoon Palace", category="sightseeing",
        catalog_category="other", latitude=24.6, longitude=73.7, cost=0, visit_minutes=60,
        preference_score=0.5, data_source="osm", cost_known=False,
        raw_tags={"tourism": "attraction", "historic": "yes", "fee": "yes"},
    )
    result = estimate_trip_budget(
        trip=trip, attractions=[item], data_source="osm",
        days=[{"day_number": 1, "date": "2026-12-01", "stops": [{"attraction_id": item.id, "name": item.name}]}],
    )
    fees = next(category for category in result["complete_budget"]["categories"] if category["key"] == "attraction_fees")
    detail = result["attraction_fee_details"][0]

    assert detail["category"] == "other"
    assert detail["estimate_category"] == "historical"
    assert detail["estimate_type"] == "category"
    assert detail["status"] == "estimated"
    assert (detail["lower"], detail["representative"], detail["upper"]) == (100, 300, 1000)
    assert fees["status"] == "estimated"
    assert fees["verified_count"] == 0
    assert fees["estimated_count"] == 1
    assert result["is_complete"] is True


@pytest.mark.parametrize("attraction_id", ["osm:node:3234257854", "osm:node:6687057486"])
def test_ghat_fee_is_unresolved_without_explicit_estimate(attraction_id):
    item = AttractionInput(
        id=attraction_id, name="Ghat", category="sightseeing", catalog_category="other",
        latitude=24.6, longitude=73.7, cost=0, visit_minutes=60, preference_score=0.5,
        data_source="osm", cost_known=False,
    )
    result = estimate_trip_budget(
        trip=make_trip(), attractions=[item], data_source="osm",
        days=[{"day_number": 1, "date": "2026-12-01", "stops": [{"attraction_id": attraction_id, "name": "Ghat"}]}],
    )
    detail = result["attraction_fee_details"][0]
    fees = next(category for category in result["complete_budget"]["categories"] if category["key"] == "attraction_fees")

    assert detail["status"] == "unavailable"
    assert detail["estimate_type"] == "unresolved"
    assert detail["original_fee_available"] is False
    assert detail["original_fee_status"] is None
    assert detail["lower"] is None
    assert fees["verified_count"] == 0
    assert fees["estimated_count"] == 0
    assert fees["unresolved_count"] == 1


def test_full_udaipur_sized_scheduled_set_is_unique_and_has_daily_fee_totals():
    category_counts = [
        *("historical" for _ in range(6)), *("museum" for _ in range(5)),
        "religious", *("park" for _ in range(3)), *("viewpoint" for _ in range(6)),
        *("cultural" for _ in range(5)),
    ]
    items = [
        AttractionInput(
            id=f"osm:test:{index}", name=f"Scheduled {index}", category=category,
            catalog_category=category, latitude=24.6, longitude=73.7, cost=0,
            visit_minutes=60, preference_score=0.5, data_source="osm", cost_known=False,
            raw_tags={"fee": "yes"} if category in {"historical", "museum"} else {},
        )
        for index, category in enumerate(category_counts)
    ]
    monsoon = AttractionInput(
        id="osm:way:111334933", name="Sajjan Garh - Monsoon Palace", category="sightseeing",
        catalog_category="other", latitude=24.6, longitude=73.7, cost=0, visit_minutes=60,
        preference_score=0.5, data_source="osm", cost_known=False,
        raw_tags={"tourism": "attraction", "historic": "yes", "fee": "yes"},
    )
    ghats = [
        AttractionInput(
            id=attraction_id, name=name, category="sightseeing", catalog_category="other",
            latitude=24.6, longitude=73.7, cost=0, visit_minutes=60, preference_score=0.5,
            data_source="osm", cost_known=False,
        )
        for attraction_id, name in (
            ("osm:node:3234257854", "Gangaur Ghat"),
            ("osm:node:6687057486", "Ambrai Ghat"),
        )
    ]
    items.extend([monsoon, *ghats])
    # Six actual itinerary days; the final day repeats one ID to verify trip-wide deduplication.
    days = [
        {"day_number": i + 1, "date": f"2026-12-0{i + 1}",
         "stops": [{"attraction_id": item.id, "name": item.name} for item in items[i * 5:(i + 1) * 5]]}
        for i in range(5)
    ]
    days.append({"day_number": 6, "date": "2026-12-06", "stops": [
        {"attraction_id": item.id, "name": item.name} for item in items[25:]
    ] + [{"attraction_id": items[0].id, "name": items[0].name}]})

    result = estimate_trip_budget(trip=make_trip(), attractions=items, data_source="osm", days=days)
    fees = next(category for category in result["complete_budget"]["categories"] if category["key"] == "attraction_fees")
    daily = result["daily_attraction_fees"]

    assert len(result["attraction_fee_details"]) == 29
    assert len({detail["attraction_id"] for detail in result["attraction_fee_details"]}) == 29
    assert fees["status"] == "partial"
    assert fees["verified_count"] == 0
    assert fees["estimated_count"] == 12
    assert fees["unresolved_count"] == 17
    assert fees["amount"] == 3600
    assert fees["range_min"] == 1200
    assert fees["range_max"] == 12000
    assert len(daily) == 6
    assert sum(day["representative_total"] for day in daily) == fees["amount"]
    assert sum(day["lower_total"] for day in daily) == fees["range_min"]
    assert sum(day["upper_total"] for day in daily) == fees["range_max"]
    assert daily[-1]["scheduled_unique_attraction_count"] == 5
    assert daily[-1]["fee_counted_attraction_count"] == 4
    serialized = json.loads(json.dumps(result["daily_attraction_fees"]))
    assert serialized[0]["attractions"][0]["estimate_type"] in {"category", "attraction_specific"}


def test_daily_fee_breakdown_marks_empty_days_and_missing_attraction_inputs():
    trip = make_trip()
    estimate = estimate_trip_budget(
        trip=trip,
        attractions=[],
        data_source="osm",
        days=[
            {"day_number": 1, "date": "2026-12-01", "stops": []},
            {"day_number": 2, "date": "2026-12-02", "stops": [{"attraction_id": "missing", "name": "Missing"}]},
        ],
    )
    first, second = estimate["daily_attraction_fees"]

    assert first["status"] == "no_attractions"
    assert first["scheduled_unique_attraction_count"] == 0
    assert first["representative_total"] == 0
    assert second["status"] == "unavailable"
    assert second["unresolved_attraction_count"] == 1
    assert second["attractions"][0]["name"] == "Missing"
    assert second["attractions"][0]["representative"] is None


def test_complete_trip_total_ranges_and_upper_bound_feasibility_with_estimated_fees():
    options = {
        **make_trip().planning_options,
        "intercity_outbound_cost": {"amount": 5000, "currency": "INR", "status": "user_provided"},
        "intercity_return_cost": {"amount": 5000, "currency": "INR", "status": "user_provided"},
        "miscellaneous_budget": 10000,
        "miscellaneous_budget_mode": "manual",
    }
    trip = make_trip(budget=85000, start_date=date(2026, 12, 1), end_date=date(2026, 12, 6), planning_options=options)
    fee_items = [AttractionInput(
        id=f"fee-{i}", name=f"Fee {i}", category="history", latitude=26.92, longitude=75.82,
        cost=0, visit_minutes=60, preference_score=0.5, cost_known=False, raw_tags={"fee": "yes"},
    ) for i in range(29)]
    days = [{"day_number": i + 1, "date": f"2026-12-0{i + 1}", "stops": [
        {"attraction_id": item.id} for item in fee_items[i::6]
    ]} for i in range(6)]
    result = estimate_trip_budget(trip=trip, attractions=fee_items, days=days, data_source="osm")
    complete = result["complete_budget"]
    categories = complete["categories"]

    assert complete["completeness"] == "complete"
    assert complete["total_estimate"] == pytest.approx(sum(item["amount"] for item in categories))
    assert complete["total_estimate_range_min"] == pytest.approx(sum(
        item.get("range_min") if item.get("range_min") is not None else item["amount"]
        for item in categories
    ))
    assert complete["total_estimate_range_max"] == pytest.approx(sum(
        item.get("range_max") if item.get("range_max") is not None else item["amount"]
        for item in categories
    ))
    assert complete["within_budget"] is (complete["total_estimate_range_max"] <= trip.budget)
    assert complete["within_budget"] is False
    assert complete["remaining_budget"] == pytest.approx(trip.budget - complete["total_estimate_range_max"])


def test_pdf_uses_backend_daily_fee_breakdown_and_labels_estimates_as_unverified():
    from app.services.itinerary_pdf import _document_lines

    trip = make_trip()
    item = AttractionInput(
        id="pdf-estimate", name="Museum", category="history", latitude=26.92,
        longitude=75.82, cost=0, visit_minutes=60, preference_score=0.5,
        data_source="osm", cost_known=False, raw_tags={"fee": "yes"},
    )
    estimate = estimate_trip_budget(
        trip=trip, attractions=[item], data_source="osm",
        days=[{"day_number": 1, "date": "2026-12-01", "stops": [{"attraction_id": item.id,
                 "name": item.name, "cost": 0, "arrival_minute": 540, "departure_minute": 600}]}],
    )
    trip.planning_inputs = {"attractions": [item.model_dump(mode="json")]}
    trip.latest_itinerary = {"days": [{"day_number": 1, "date": "2026-12-01", "stops": [
        {"attraction_id": item.id, "name": item.name, "cost": 0, "arrival_minute": 540, "departure_minute": 600},
    ]}], "budget_estimate": estimate}
    text = " ".join(line for _, line in _document_lines(trip))

    assert "Estimated fee allowance ₹300 (not verified)" in text
    assert "Daily attraction fee estimates" in text
    assert "Estimated: ₹300 (not verified)" in text


def test_miscellaneous_contingency_is_range_based_non_circular_and_legacy_total_is_unchanged():
    options = {**make_trip().planning_options, "miscellaneous_budget": 0,
               "intercity_outbound_cost": {"amount": 100, "currency": "INR", "status": "user_provided"},
               "intercity_return_cost": {"amount": 100, "currency": "INR", "status": "user_provided"}}
    trip = make_trip(planning_options=options)
    result = estimate_trip_budget(trip=trip, days=[], attractions=[], data_source="osm")
    complete = result["complete_budget"]
    misc = next(item for item in complete["categories"] if item["key"] == "miscellaneous")
    base = sum(item["amount"] for item in complete["categories"] if item["key"] != "miscellaneous")
    assert misc["status"] == "estimated"
    assert misc["amount"] == pytest.approx(round(base * 0.1, 2))
    assert misc["range_min"] <= misc["amount"] <= misc["range_max"]
    assert result["total_estimated"] == sum(item["amount"] or 0 for item in result["categories"])


@pytest.mark.parametrize(("mode", "amount", "status"), [
    ("manual", 0, "user_provided"), ("disabled", None, "unavailable"),
])
def test_miscellaneous_manual_zero_and_disabled_modes(mode, amount, status):
    options = {**make_trip().planning_options, "miscellaneous_budget": 0,
               "miscellaneous_budget_mode": mode}
    result = estimate_trip_budget(trip=make_trip(planning_options=options), days=[],
                                  attractions=[], data_source="osm")
    misc = next(item for item in result["complete_budget"]["categories"] if item["key"] == "miscellaneous")
    assert misc["amount"] == amount
    assert misc["status"] == status


def test_fixed_cost_reservation_respects_miscellaneous_mode():
    base_options = {**make_trip().planning_options, "miscellaneous_budget": 0}
    baseline = attraction_budget_after_fixed_costs(make_trip(planning_options=base_options))
    automatic = attraction_budget_after_fixed_costs(make_trip(planning_options={
        **base_options, "miscellaneous_budget": 500, "miscellaneous_budget_mode": "automatic",
    }))
    manual = attraction_budget_after_fixed_costs(make_trip(planning_options={
        **base_options, "miscellaneous_budget": 500, "miscellaneous_budget_mode": "manual",
    }))
    disabled = attraction_budget_after_fixed_costs(make_trip(planning_options={
        **base_options, "miscellaneous_budget": 500, "miscellaneous_budget_mode": "disabled",
    }))
    assert automatic == baseline
    assert disabled == baseline
    assert manual == baseline - 500


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
            # The saved-plan budget counts scheduled fees, never a bare day total.
            "days": [{"stops": [ItineraryStop(
                attraction_id="museum", name="Museum", arrival_minute=540,
                departure_minute=600, travel_minutes_before=0, cost=2000,
                preference_score=0.8, risk_score=None,
            )], "warnings": [], "total_cost": 2000}],
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
            "visit_minutes": 60, "preference_score": 0.8, "cost_known": True,
            "fee_status": "verified", "fee_currency": "INR", "fee_pricing_basis": "group",
            "fee_source": "Verified test fixture",
        }],
        data_source="user_supplied",
    )
    result = trips_api._build_saved_multiday_plan(trip, request)
    estimate = result["budget_estimate"]

    assert seen_budgets == [1500]
    assert estimate["within_budget"] is True  # legacy destination-only status
    categories = {
        category["key"]: category
        for category in estimate["complete_budget"]["categories"]
    }
    assert categories["intercity_outbound"]["amount"] == 2000
    assert categories["intercity_return"]["amount"] == 2000
    assert categories["attraction_fees"]["amount"] == 2000
    assert categories["attraction_fees"]["status"] == "verified"
    assert categories["miscellaneous"]["amount"] == 100
    assert categories["miscellaneous"]["status"] == "user_provided"
    assert estimate["complete_budget"]["total_estimate"] == 15500
    assert estimate["complete_budget"]["total_estimate_range_min"] == 13060
    assert estimate["complete_budget"]["total_estimate_range_max"] == 19440
    assert estimate["complete_budget"]["remaining_budget"] == -4440
    assert estimate["complete_budget"]["within_budget"] is False
    assert result["feasible"] is False
    assert any("complete-trip costs exceed the budget by ₹500" in warning for warning in result["warnings"])
