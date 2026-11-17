from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.services import weather, weather_replanning
from app.services.weather_risk import assess_weather_risk


def _payload(lat=26.9, lon=75.8, **values):
    return {"latitude": lat, "longitude": lon, "timezone": "Asia/Kolkata", "hourly": {
        "time": ["2026-12-01T14:00", "2026-12-01T15:00"],
        "precipitation_probability": values.get("probability", [80, None]),
        "precipitation": values.get("precipitation", [4.0, None]),
        "temperature_2m": values.get("temperature", [30, None]),
        "apparent_temperature": values.get("apparent", [32, None]),
        "wind_speed_10m": values.get("wind", [12, None]),
        "weather_code": values.get("code", [61, None]),
    }}


def test_open_meteo_parser_keeps_missing_values_unknown_and_cache(monkeypatch):
    weather.clear_weather_cache()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_payload(probability=[None, None]))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    points = [(26.9, 75.8), (26.9, 75.8)]
    first = weather.fetch_forecasts(points, endpoint="https://weather.test", client=client)
    second = weather.fetch_forecasts(points, endpoint="https://weather.test", client=client)
    assert len(calls) == 1
    parsed = weather.forecast_at(first[(26.9, 75.8)], datetime.fromisoformat("2026-12-01T14:00:00+05:30"))
    assert parsed["forecast_time"] == "2026-12-01T14:00"
    assert parsed["values"]["precipitation_probability"] is None
    assert second == first


def test_provider_http_failure_is_explicit():
    weather.clear_weather_cache()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(weather.WeatherProviderError):
        weather.fetch_forecasts([(26.9, 75.8)], endpoint="https://weather.test", client=client)


def test_coordinates_are_batched_in_bounded_provider_requests():
    weather.clear_weather_cache()
    calls = []

    def handler(request):
        calls.append(request)
        latitudes = [float(value) for value in request.url.params["latitude"].split(",")]
        longitudes = [float(value) for value in request.url.params["longitude"].split(",")]
        payloads = [_payload(lat, lon) for lat, lon in zip(latitudes, longitudes)]
        return httpx.Response(200, json=payloads if len(payloads) > 1 else payloads[0])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    points = [(26.0 + index / 1000, 75.0 + index / 1000) for index in range(51)]
    result = weather.fetch_forecasts(points, endpoint="https://weather-batch.test", client=client)
    assert len(calls) == 2
    assert len(result) == 51


def test_weather_risk_distinguishes_unknown_indoor_and_outdoor():
    empty = {"forecast_time": "2026-12-01T14:00", "values": {"precipitation_probability": None}}
    outdoor = {"category": "viewpoint", "raw_tags": {}}
    indoor = {"category": "museum", "raw_tags": {}}
    ambiguous = {"category": "historical", "raw_tags": {}}
    assert assess_weather_risk(outdoor, empty, retrieved_at="now")["known"] is False
    assert assess_weather_risk(ambiguous, {"forecast_time": "2026-12-01T14:00", "values": {"precipitation_probability": 0}}, retrieved_at="now")["score"] is None
    complete_clear = {"forecast_time": "2026-12-01T14:00", "values": {
        "precipitation_probability": 0, "precipitation": 0, "temperature_2m": 27,
        "apparent_temperature": 26, "wind_speed_10m": 6.5, "weather_code": 0,
    }}
    clear_risk = assess_weather_risk(outdoor, complete_clear, retrieved_at="2026-11-30T00:00:00+00:00")
    assert clear_risk["known"] is True
    assert clear_risk["score"] == 0
    assert clear_risk["condition"] == "Clear"
    assert clear_risk["condition_kind"] == "sun"
    assert clear_risk["forecast_time"] == "2026-12-01T14:00"
    assert clear_risk["retrieved_at"] == "2026-11-30T00:00:00+00:00"
    partly_cloudy = {**complete_clear, "values": {**complete_clear["values"], "weather_code": 2}}
    assert assess_weather_risk(outdoor, partly_cloudy, retrieved_at="now")["condition"] == "Partly cloudy"

    heavy_rain = {"forecast_time": "2026-12-01T14:00", "values": {
        "precipitation_probability": 90, "precipitation": 4, "temperature_2m": 27,
        "apparent_temperature": 26, "wind_speed_10m": 6.5, "weather_code": 61,
    }}
    rain_risk = assess_weather_risk(outdoor, heavy_rain, retrieved_at="now")
    assert rain_risk["known"] is True
    assert rain_risk["score"] == 0.9
    assert {item["type"] for item in rain_risk["advisories"]} == {"rain", "precipitation"}

    high_heat = {**complete_clear, "values": {**complete_clear["values"], "temperature_2m": 41,
        "apparent_temperature": 42, "weather_code": 0}}
    heat_risk = assess_weather_risk(outdoor, high_heat, retrieved_at="now")
    assert any(item["type"] == "temperature" for item in heat_risk["advisories"])
    assert heat_risk["advisory_score"] >= 0.65

    missing_precipitation = {**complete_clear, "values": {key: value for key, value in complete_clear["values"].items() if key != "precipitation_probability"}}
    partial = assess_weather_risk(outdoor, missing_precipitation, retrieved_at="now")
    assert partial["known"] is False
    assert partial["score"] is None
    assert partial["confidence"] == "partial"
    assert "precipitation_probability" not in partial["variables"]

    missing_temperature = {**complete_clear, "values": {key: value for key, value in complete_clear["values"].items() if key not in {"temperature_2m", "apparent_temperature"}}}
    assert assess_weather_risk(outdoor, missing_temperature, retrieved_at="now")["score"] is None

    indoor_risk = assess_weather_risk(indoor, complete_clear, retrieved_at="now")
    assert indoor_risk["known"] is True
    assert indoor_risk["score"] == 0
    assert indoor_risk["data_kind"] == "forecast"


def test_weather_assessment_with_no_provider_values_is_unavailable():
    result = assess_weather_risk(
        {"category": "viewpoint", "raw_tags": {}},
        {"forecast_time": None, "values": {}},
        retrieved_at="now",
    )
    assert result["known"] is False
    assert result["score"] is None
    assert result["confidence"] == "unavailable"
    assert result["variables"] == {}


def test_weather_replan_preserves_completed_and_unaffected_days(monkeypatch):
    original = {
        "trip_id": 1, "algorithm": "greedy_multiday", "data_source": "osm", "total_cost": 100,
        "total_travel_minutes": 20, "total_visit_minutes": 180, "satisfaction": 0.8,
        "risk_score": None, "risk_data_status": "unavailable", "feasible": True, "warnings": [],
        "days": [
            {"day_number": 1, "date": "2026-12-01", "stops": [
                {"attraction_id": "view", "name": "Viewpoint", "arrival_minute": 840, "departure_minute": 900,
                 "travel_minutes_before": 10, "cost": 10, "preference_score": 0.8, "risk_score": None}],
             "total_cost": 10, "total_travel_minutes": 10, "total_visit_minutes": 60, "feasible": True, "warnings": []},
            {"day_number": 2, "date": "2026-12-02", "stops": [
                {"attraction_id": "museum", "name": "Museum", "arrival_minute": 600, "departure_minute": 720,
                 "travel_minutes_before": 10, "cost": 90, "preference_score": 0.8, "risk_score": None}],
             "total_cost": 90, "total_travel_minutes": 10, "total_visit_minutes": 120, "feasible": True, "warnings": []},
        ],
    }
    attractions = [
        {"id": "view", "name": "Viewpoint", "category": "viewpoint", "latitude": 26.9, "longitude": 75.8, "cost": 10, "visit_minutes": 60, "preference_score": .8, "raw_tags": {}},
        {"id": "museum", "name": "Museum", "category": "museum", "latitude": 26.91, "longitude": 75.81, "cost": 90, "visit_minutes": 120, "preference_score": .8, "raw_tags": {"tourism": "museum"}},
        {"id": "temple", "name": "Temple", "category": "religious", "latitude": 26.901, "longitude": 75.801, "cost": 5, "visit_minutes": 45, "preference_score": .7, "raw_tags": {"amenity": "place_of_worship"}},
    ]

    def fake_fetch(points, **kwargs):
        return {point: {"provider": "open-meteo", "retrieved_at": "2026-11-30T00:00:00+00:00", "timezone": "Asia/Kolkata",
                        "hourly": {"precipitation_probability": {"2026-12-01T14:00": 90},
                                   "precipitation": {"2026-12-01T14:00": 4}, "temperature_2m": {},
                                   "apparent_temperature": {}, "wind_speed_10m": {}, "weather_code": {}}}
                for point in points}
    monkeypatch.setattr(weather_replanning, "fetch_forecasts", fake_fetch)
    trip = SimpleNamespace(latest_itinerary=original, planning_inputs={"attractions": attractions}, start_date="2026-12-01",
                           completed_attraction_ids=["view"], itinerary_revision=3, start_latitude=26.9, start_longitude=75.8,
                           planning_options={}, preferences={}, available_minutes_per_day=1200, budget=500)
    proposal = weather_replanning.build_weather_proposal(trip, day_number=1, now=datetime(2026, 11, 30, tzinfo=timezone.utc))
    assert proposal["mode"] == "forecast"
    assert proposal["revised_stops"][0]["attraction_id"] == "view"
    assert proposal["revised_itinerary"]["days"][1] == original["days"][1]
    assert trip.latest_itinerary == original
    assert proposal["attribution"] == weather.ATTRIBUTION
    assert proposal["forecast_available"] is True
    assert proposal["can_accept"] is True
    assert any("coverage is partial" in warning for warning in proposal["warnings"])

    monkeypatch.setattr(weather_replanning, "fetch_forecasts", lambda points, **kwargs: {
        point: {"provider": "open-meteo", "retrieved_at": "2026-11-30T00:00:00+00:00",
                "timezone": "Asia/Kolkata", "hourly": {}} for point in points
    })
    unavailable = weather_replanning.build_weather_proposal(trip, day_number=1, now=datetime(2026, 11, 30, tzinfo=timezone.utc))
    assert unavailable["forecast_available"] is False
    assert unavailable["can_accept"] is False
    assert unavailable["revised_stops"][0]["attraction_id"] == original["days"][0]["stops"][0]["attraction_id"]
    assert unavailable["revised_stops"][0]["arrival_minute"] == original["days"][0]["stops"][0]["arrival_minute"]
    assert unavailable["revised_stops"][0]["weather_assessment"]["score"] is None
