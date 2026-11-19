"""Configurable, explicitly approximate transportation cost estimates.

No result from this module is a ticket quote. City geocoding is user-triggered,
cached in-process, and rate limited when the public Nominatim service is used.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import httpx

from app.services.routing import haversine_km


GEOCODING_ATTRIBUTION = "© OpenStreetMap contributors"
_LOCATION_CACHE: OrderedDict[str, dict[str, Any] | None] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_NOMINATIM_LOCK = threading.Lock()
_LAST_NOMINATIM_REQUEST = 0.0
_CACHE_LIMIT = 512


def _rate(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, default))
        return value if isfinite(value) and value >= 0 else default
    except (TypeError, ValueError):
        return default


def _city_key(city: str) -> str:
    return " ".join(city.strip().casefold().split())


def resolve_city(city: str, latitude: float | None = None, longitude: float | None = None) -> dict[str, Any] | None:
    """Return explicit coordinates or a cached/user-triggered Indian city lookup."""
    if latitude is not None and longitude is not None:
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return {"latitude": float(latitude), "longitude": float(longitude), "source": "provided_coordinates", "display_name": city}
        return None
    key = _city_key(city)
    if not key:
        return None
    with _CACHE_LOCK:
        if key in _LOCATION_CACHE:
            result = _LOCATION_CACHE.pop(key)
            _LOCATION_CACHE[key] = result
            return dict(result) if result else None

    provider = os.getenv("GEOCODING_PROVIDER", "nominatim").strip().lower()
    if provider in {"none", "disabled", ""}:
        return None
    if provider != "nominatim":
        # Other providers can implement this module boundary without changing budgets.
        return None

    global _LAST_NOMINATIM_REQUEST
    base_url = os.getenv("GEOCODING_BASE_URL", "https://nominatim.openstreetmap.org/search").strip()
    user_agent = os.getenv("GEOCODING_USER_AGENT", "GoWander/1.0 (user-triggered city route estimate)").strip()
    try:
        # Nominatim requires no more than one request/second per application.
        with _NOMINATIM_LOCK:
            with _CACHE_LOCK:
                if key in _LOCATION_CACHE:
                    cached = _LOCATION_CACHE.pop(key)
                    _LOCATION_CACHE[key] = cached
                    return dict(cached) if cached else None
            wait = 1.0 - (time.monotonic() - _LAST_NOMINATIM_REQUEST)
            if wait > 0:
                time.sleep(wait)
            _LAST_NOMINATIM_REQUEST = time.monotonic()
            with httpx.Client(timeout=5.0, headers={"User-Agent": user_agent}) as client:
                response = client.get(base_url, params={"q": f"{city}, India", "format": "jsonv2", "limit": 1, "countrycodes": "in", "featureType": "city"})
                response.raise_for_status()
                payload = response.json()
        first = payload[0] if isinstance(payload, list) and payload else None
        result = None
        if isinstance(first, dict):
            lat, lon = float(first["lat"]), float(first["lon"])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                result = {"latitude": lat, "longitude": lon, "source": "nominatim", "display_name": str(first.get("display_name") or city)}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        result = None
    with _CACHE_LOCK:
        _LOCATION_CACHE[key] = result
        while len(_LOCATION_CACHE) > _CACHE_LIMIT:
            _LOCATION_CACHE.popitem(last=False)
    return dict(result) if result else None


def resolve_route_distance_km(origin: dict[str, Any], destination: dict[str, Any]) -> tuple[float, str]:
    """Use configured OSRM road distance when enabled, otherwise a disclosed proxy."""
    provider = os.getenv("ROUTING_PROVIDER", "haversine").strip().lower()
    if provider == "osrm":
        base = os.getenv("ROUTING_OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
        coords = f"{origin['longitude']},{origin['latitude']};{destination['longitude']},{destination['latitude']}"
        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.get(f"{base}/route/v1/driving/{coords}", params={"overview": "false", "steps": "false"})
                response.raise_for_status()
                payload = response.json()
            routes = payload.get("routes") if isinstance(payload, dict) else None
            meters = routes[0].get("distance") if routes else None
            if isinstance(meters, (int, float)) and isfinite(meters) and meters > 0:
                return float(meters) / 1000, "osrm_road_route"
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
            pass
    air = haversine_km((origin["latitude"], origin["longitude"]), (destination["latitude"], destination["longitude"]))
    return air * _rate("TRIP_INTERCITY_ROAD_DISTANCE_FACTOR", 1.3), "provisional_road_distance_from_straight_line"


def _estimate_mode(mode: str, air_km: float, road_km: float, travelers: int, road_basis: str) -> dict[str, Any]:
    key = mode.lower().replace(" ", "_")
    at = datetime.now(timezone.utc).isoformat()
    assumptions: list[str] = ["Configurable planning estimate only; not a live fare, booking price, or availability check."]
    if key == "train":
        distance = air_km * _rate("TRIP_TRAIN_DISTANCE_FACTOR", 1.2)
        low = max(_rate("TRIP_TRAIN_MIN_FARE_INR", 100), distance * _rate("TRIP_TRAIN_RATE_LOW_INR_PER_PASSENGER_KM", 0.8)) * travelers
        high = max(_rate("TRIP_TRAIN_MIN_FARE_INR", 100), distance * _rate("TRIP_TRAIN_RATE_HIGH_INR_PER_PASSENGER_KM", 2.5)) * travelers
        basis = "per_passenger"
        assumptions.append(f"Approximate rail distance is {distance:.1f} km (straight-line distance × configured factor); no railway route or class was checked; {travelers} traveler(s).")
    elif key == "bus":
        distance = air_km * _rate("TRIP_INTERCITY_ROAD_DISTANCE_FACTOR", 1.3)
        low = max(_rate("TRIP_BUS_MIN_FARE_INR", 100), distance * _rate("TRIP_BUS_RATE_LOW_INR_PER_PASSENGER_KM", 1.2)) * travelers
        high = max(_rate("TRIP_BUS_MIN_FARE_INR", 100), distance * _rate("TRIP_BUS_RATE_HIGH_INR_PER_PASSENGER_KM", 2.2)) * travelers
        basis = "per_passenger"
        assumptions.append(f"Approximate road distance is {distance:.1f} km from straight-line distance; no bus route or operator was checked; {travelers} traveler(s).")
    elif key == "flight":
        low = (_rate("TRIP_FLIGHT_BASE_FARE_LOW_INR", 800) + air_km * _rate("TRIP_FLIGHT_RATE_LOW_INR_PER_KM", 5)) * travelers
        high = (_rate("TRIP_FLIGHT_BASE_FARE_HIGH_INR", 1800) + air_km * _rate("TRIP_FLIGHT_RATE_HIGH_INR_PER_KM", 10)) * travelers
        distance = air_km
        basis = "per_passenger"
        assumptions.append(f"Geographic air distance is {distance:.1f} km; model has no date, airline, baggage, airport transfer, or seat data; {travelers} traveler(s).")
    elif key == "private_car":
        distance = road_km
        toll_low = _rate("TRIP_PRIVATE_CAR_TOLL_ALLOWANCE_LOW_INR", 0)
        toll_high = _rate("TRIP_PRIVATE_CAR_TOLL_ALLOWANCE_HIGH_INR", 800)
        low = distance * _rate("TRIP_PRIVATE_CAR_RATE_LOW_INR_PER_KM", 12) + toll_low
        high = distance * _rate("TRIP_PRIVATE_CAR_RATE_HIGH_INR_PER_KM", 18) + toll_high
        basis = "per_vehicle"
        assumptions.append(f"One vehicle, not per passenger. Road distance basis: {road_basis} ({distance:.1f} km); configured operating cost and toll allowance; traveler count does not multiply vehicle cost.")
    else:
        return {"status": "unavailable", "amount": None, "mode": mode, "assumptions": ["Unsupported intercity transportation mode."]}
    low, high = round(min(low, high), 2), round(max(low, high), 2)
    return {"status": "estimated", "amount": round((low + high) / 2, 2), "range_min": low, "range_max": high,
            "representative_amount": round((low + high) / 2, 2), "mode": mode, "unit_basis": basis,
            "amount_basis": "whole_group_total",
            "traveler_count": travelers, "distance_km": round(distance, 2), "estimated_at": at,
            "source": "configurable_transport_model", "method": key, "assumptions": assumptions}


def estimate_intercity_transport(
    origin: str, destination: str, travelers: int, mode: str | None,
    origin_latitude: float | None = None, origin_longitude: float | None = None,
    destination_latitude: float | None = None, destination_longitude: float | None = None,
) -> dict[str, Any]:
    origin_location = resolve_city(origin, origin_latitude, origin_longitude)
    destination_location = resolve_city(destination, destination_latitude, destination_longitude)
    unavailable = {"status": "unavailable", "amount": None, "source": None, "assumptions": ["Origin or destination coordinates are unavailable; no route distance or fare estimate was invented."], "mode": mode}
    if not origin_location or not destination_location:
        return {"origin": origin_location, "destination": destination_location, "distance_km": None,
                "distance_basis": "unavailable", "outbound": dict(unavailable), "return": dict(unavailable),
                "provisional": mode is None, "attribution": GEOCODING_ATTRIBUTION if origin_location or destination_location else None}
    air_km = haversine_km((origin_location["latitude"], origin_location["longitude"]), (destination_location["latitude"], destination_location["longitude"]))
    road_km, road_basis = resolve_route_distance_km(origin_location, destination_location)
    modes = [mode] if mode in {"train", "bus", "flight", "private_car"} else ["train", "bus", "flight", "private_car"]
    by_mode = {candidate: _estimate_mode(candidate, air_km, road_km, travelers, road_basis) for candidate in modes}
    if mode in by_mode:
        outbound = dict(by_mode[mode])
        returning = dict(by_mode[mode])
        for item, direction in ((outbound, "Outbound"), (returning, "Return")):
            item["assumptions"] = [*item["assumptions"], f"{direction} leg uses the same configured distance model; no direction-specific schedules or fares were available."]
    else:
        available = [item for item in by_mode.values() if item.get("status") == "estimated"]
        low = min((item["range_min"] for item in available), default=None)
        high = max((item["range_max"] for item in available), default=None)
        representative = round((low + high) / 2, 2) if low is not None and high is not None else None
        assumptions = ["Provisional mode-agnostic planning allowance spanning available train, bus, flight, and private-car models; select a mode to narrow it.", "Not a confirmed fare; modeled ranges are configuration assumptions."]
        if road_basis != "osrm_road_route":
            assumptions.append("Private-car leg uses a provisional road-distance proxy, not a verified road route.")
        outbound = {"status": "estimated" if representative is not None else "unavailable", "amount": representative, "representative_amount": representative,
                    "range_min": low, "range_max": high, "mode": None, "unit_basis": "mode_agnostic",
                    "amount_basis": "whole_group_total",
                    "traveler_count": travelers, "estimated_at": datetime.now(timezone.utc).isoformat(),
                    "source": "configurable_transport_model", "method": "provisional_mode_range", "assumptions": assumptions,
                    "mode_estimates": by_mode}
        returning = {**outbound, "assumptions": [*assumptions, "Return leg is a separate category using the same mode-agnostic configured model; no directional fare data is available."]}
    geocoding_note = "Coordinates were supplied by the traveler." if origin_location.get("source") == "provided_coordinates" and destination_location.get("source") == "provided_coordinates" else "City coordinates resolved through the configured Nominatim geocoder; place matching may be approximate. © OpenStreetMap contributors."
    for item in (outbound, returning):
        item["assumptions"] = [*item.get("assumptions", []), geocoding_note]
    return {"origin": origin_location, "destination": destination_location, "distance_km": round(air_km, 2),
            "road_distance_km": round(road_km, 2), "distance_basis": road_basis,
            "outbound": outbound, "return": returning, "provisional": mode is None,
            "attribution": GEOCODING_ATTRIBUTION if origin_location.get("source") == "nominatim" or destination_location.get("source") == "nominatim" else None}


def validate_manual_amount(amount: float, estimate: dict[str, Any] | None, *, zero_fare_confirmed: bool = False, override_confirmed: bool = False) -> dict[str, Any]:
    if not isinstance(amount, (int, float)) or not isfinite(float(amount)) or amount < 0:
        raise ValueError("Enter a finite, non-negative whole-group amount.")
    if amount > 5_000_000:
        raise ValueError("The maximum transportation override is INR 5,000,000 per leg.")
    if amount == 0 and not zero_fare_confirmed:
        return {"confirmation_required": True, "warning": "Confirm that this transportation leg is genuinely free before saving zero."}
    if amount == 0 and zero_fare_confirmed:
        return {"confirmation_required": False, "warning": None}
    if estimate and estimate.get("status") == "estimated" and isinstance(estimate.get("range_min"), (int, float)) and isinstance(estimate.get("range_max"), (int, float)):
        low, high = float(estimate["range_min"]), float(estimate["range_max"])
        if amount < low * 0.5 or amount > max(high * 2, high + 5000):
            if not override_confirmed:
                return {"confirmation_required": True, "warning": f"This amount is outside the broad indicative range INR {low:,.0f}–{high:,.0f}. Confirm it is intentional; the value will not be changed."}
    return {"confirmation_required": False, "warning": None}


def manual_cost_record(amount: float, estimate: dict[str, Any] | None, *, zero_fare_confirmed: bool = False, override_confirmed: bool = False) -> dict[str, Any]:
    result = validate_manual_amount(amount, estimate, zero_fare_confirmed=zero_fare_confirmed, override_confirmed=override_confirmed)
    if result["confirmation_required"]:
        raise ValueError(result["warning"])
    metadata = estimate or {}
    assumptions = [*list((estimate or {}).get("assumptions") or []), "Traveler-entered whole-group total for this leg; not a provider quote."]
    if result["warning"]:
        assumptions.append(result["warning"])
    return {"amount": float(amount), "currency": "INR", "status": "user_provided", "source": "User input",
            "assumptions": assumptions, "mode": metadata.get("mode"), "unit_basis": metadata.get("unit_basis"),
            "amount_basis": "whole_group_total",
            "traveler_count": metadata.get("traveler_count"), "range_min": metadata.get("range_min"),
            "range_max": metadata.get("range_max"), "distance_km": metadata.get("distance_km"),
            "estimated_at": metadata.get("estimated_at"), "method": metadata.get("method"),
            "zero_fare_confirmed": zero_fare_confirmed, "override_confirmed": override_confirmed}


def intercity_cost_record(estimate: dict[str, Any]) -> dict[str, Any]:
    """Return an additive TripPlanningOptions-compatible per-leg cost record."""
    if estimate.get("status") != "estimated" or estimate.get("amount") is None:
        return {"amount": None, "currency": "INR", "status": "unavailable", "source": None,
                "assumptions": list(estimate.get("assumptions") or []), "mode": estimate.get("mode"),
                "unit_basis": estimate.get("unit_basis"), "traveler_count": estimate.get("traveler_count"),
                "amount_basis": estimate.get("amount_basis", "whole_group_total"),
                "range_min": None, "range_max": None, "distance_km": estimate.get("distance_km"),
                "estimated_at": estimate.get("estimated_at"), "method": estimate.get("method")}
    return {"amount": estimate["amount"], "currency": "INR", "status": "estimated",
            "source": estimate.get("source") or "configurable_transport_model",
            "assumptions": list(estimate.get("assumptions") or []), "mode": estimate.get("mode"),
            "unit_basis": estimate.get("unit_basis"), "traveler_count": estimate.get("traveler_count"),
            "amount_basis": estimate.get("amount_basis", "whole_group_total"),
            "range_min": estimate.get("range_min"), "range_max": estimate.get("range_max"),
            "distance_km": estimate.get("distance_km"), "estimated_at": estimate.get("estimated_at"),
            "method": estimate.get("method")}


def local_transport_cost(route_km: float, journey_count: int, mode: str, travelers: int) -> dict[str, Any]:
    """Estimate intra-destination travel, retaining legacy rate env names."""
    aliases = {
        "walk": "walking", "walking": "walking", "transit": "public transport", "metro": "public transport",
        "public_transport": "public transport", "auto": "auto", "auto/taxi": "auto", "taxi": "auto",
        "cab": "auto", "car": "private car", "private_car": "private car", "private car": "private car",
        "rental_vehicle": "rental vehicle", "rental vehicle": "rental vehicle", "mixed": "mixed",
        "bus": "public transport", "train": "public transport", "motorbike": "auto",
    }
    key = mode.strip().lower().replace("-", "_")
    canonical = aliases.get(key, aliases.get(key.replace("_", " "), key))
    if canonical == "flight":
        return {"status": "unavailable", "amount": None, "range_min": None, "range_max": None,
                "assumptions": ["Flights are intercity transportation and are not priced as local travel."]}
    if journey_count <= 0 and canonical != "walking":
        return {"status": "estimated", "amount": 0.0, "range_min": 0.0, "range_max": 0.0,
                "source": "no_scheduled_local_legs", "assumptions": ["No local travel legs were scheduled, so no local transportation expense is added."]}
    rates = {"walking": 0, "public transport": 18, "auto": 25, "private car": 12, "rental vehicle": 18, "mixed": 18}
    if canonical not in rates:
        return {"status": "unavailable", "amount": None, "range_min": None, "range_max": None,
                "assumptions": [f"No local rate model is configured for '{mode}'."]}
    env_key = "TRIP_LOCAL_FARE_INR_PER_KM_" + "".join(ch if ch.isalnum() else "_" for ch in canonical.upper())
    # Keep historical names usable when the planner selected an old mode string.
    legacy_key = "TRIP_LOCAL_FARE_INR_PER_KM_" + "".join(ch if ch.isalnum() else "_" for ch in key.upper())
    historical_alias = {"private car": "CAR", "auto": "TAXI"}.get(canonical)
    alias_key = f"TRIP_LOCAL_FARE_INR_PER_KM_{historical_alias}" if historical_alias else legacy_key
    rate = _rate(env_key, _rate(legacy_key, _rate(alias_key, rates[canonical])))
    passenger_priced = canonical == "public transport"
    amount = round(route_km * rate * (travelers if passenger_priced else 1), 2)
    if canonical == "walking":
        low = high = 0.0
        assumptions = ["Walking has no modeled paid transportation fare; lodging transfers and incidental costs are excluded."]
    else:
        low = round(amount * _rate("TRIP_LOCAL_ESTIMATE_RANGE_LOW_FACTOR", 0.75), 2)
        high = round(amount * _rate("TRIP_LOCAL_ESTIMATE_RANGE_HIGH_FACTOR", 1.35), 2)
        basis = f"{travelers} traveler(s), per passenger" if passenger_priced else "one vehicle, not multiplied by travelers"
        assumptions = [f"{route_km:.1f} straight-line km over {journey_count} scheduled local legs at INR {rate:g}/km; {basis}; not a road-route fare.",
                       "No unobserved hotel transfer, return-to-base leg, parking or toll was added."]
        if canonical == "rental vehicle":
            assumptions.append("Per-kilometre allowance excludes rental base charges, deposits, and any fees not supplied by a provider.")
        if canonical == "mixed":
            assumptions.append("Mixed mode uses one blended configurable rate because leg-by-leg mode choices are not available.")
    return {"status": "estimated", "amount": amount, "range_min": low, "range_max": high,
            "source": "configurable_distance_estimate", "assumptions": assumptions, "mode": canonical,
            "unit_basis": "per_passenger" if passenger_priced else "per_vehicle",
            "amount_basis": "whole_group_total"}
