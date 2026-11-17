"""Open-Meteo forecast retrieval with bounded batching and a short in-process cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import RLock
from time import monotonic
from typing import Any

import httpx


PROVIDER = "open-meteo"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
HOURLY = (
    "precipitation_probability,precipitation,temperature_2m,apparent_temperature,"
    "wind_speed_10m,weather_code"
)
_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = RLock()


class WeatherProviderError(RuntimeError):
    pass


def clear_weather_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def fetch_forecasts(points: list[tuple[float, float]], *, endpoint: str | None = None,
                    api_key: str | None = None, client: httpx.Client | None = None,
                    now: datetime | None = None) -> dict[tuple[float, float], dict[str, Any]]:
    """Fetch one forecast bundle per bounded coordinate batch; values remain nullable."""
    endpoint = endpoint or __import__("os").getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1/forecast")
    api_key = api_key if api_key is not None else __import__("os").getenv("OPEN_METEO_API_KEY")
    now = now or datetime.now(timezone.utc)
    unique = list(dict.fromkeys((round(lat, 5), round(lon, 5)) for lat, lon in points))
    result: dict[tuple[float, float], dict[str, Any]] = {}
    missing = []
    for point in unique:
        key = (endpoint, point)
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and cached[0] > monotonic():
                result[point] = cached[1]
                continue
            _CACHE.pop(key, None)
        missing.append(point)
    own_client = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=True)
    try:
        for offset in range(0, len(missing), 50):
            batch = missing[offset:offset + 50]
            params: dict[str, Any] = {
                "latitude": ",".join(str(p[0]) for p in batch),
                "longitude": ",".join(str(p[1]) for p in batch),
                "hourly": HOURLY, "timezone": "Asia/Kolkata", "forecast_days": 16,
            }
            if api_key:
                params["apikey"] = api_key
            try:
                response = http.get(endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise WeatherProviderError("Open-Meteo forecast request failed.") from exc
            locations = payload if isinstance(payload, list) else [payload]
            if len(locations) != len(batch):
                # One coordinate responses are objects; multi-location responses are lists.
                if len(batch) == 1 and isinstance(payload, dict):
                    locations = [payload]
                else:
                    raise WeatherProviderError("Open-Meteo returned an unexpected number of locations.")
            retrieved = now.isoformat()
            for point, location in zip(batch, locations):
                hourly = location.get("hourly") if isinstance(location, dict) else None
                times = hourly.get("time") if isinstance(hourly, dict) else None
                if not isinstance(times, list):
                    raise WeatherProviderError("Open-Meteo returned no hourly forecast timeline.")
                forecast = {
                    "provider": PROVIDER, "data_kind": "forecast", "retrieved_at": retrieved,
                    "timezone": location.get("timezone"), "grid_latitude": location.get("latitude"),
                    "grid_longitude": location.get("longitude"), "hourly": {},
                }
                for name in HOURLY.split(","):
                    values = hourly.get(name)
                    forecast["hourly"][name] = dict(zip(times, values)) if isinstance(values, list) else {}
                result[point] = forecast
                with _CACHE_LOCK:
                    _CACHE[(endpoint, point)] = (monotonic() + 1800, forecast)
    finally:
        if own_client:
            http.close()
    return result


def forecast_at(forecast: dict[str, Any], when: datetime) -> dict[str, Any]:
    """Select the scheduled local hour (nearest forecast hour, within 90 minutes)."""
    tz_name = forecast.get("timezone") or "Asia/Kolkata"
    try:
        from zoneinfo import ZoneInfo
        local = when.astimezone(ZoneInfo(tz_name)) if when.tzinfo else when.replace(tzinfo=ZoneInfo(tz_name))
    except Exception:
        local = when
    times = forecast.get("hourly", {}).get("precipitation_probability", {})
    if not times:
        times = next((series for series in forecast.get("hourly", {}).values() if series), {})
    if not times:
        return {"forecast_time": None, "values": {}}
    chosen = min(times, key=lambda value: abs(datetime.fromisoformat(value).replace(tzinfo=local.tzinfo) - local))
    gap = abs(datetime.fromisoformat(chosen).replace(tzinfo=local.tzinfo) - local)
    if gap > timedelta(minutes=90):
        return {"forecast_time": None, "values": {}}
    return {
        "forecast_time": chosen,
        "values": {name: series.get(chosen) for name, series in forecast.get("hourly", {}).items()},
    }
