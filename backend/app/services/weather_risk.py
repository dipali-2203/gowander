"""Explainable activity suitability scoring from forecast fields only."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def _condition(code: Any) -> tuple[str | None, str]:
    if code is None:
        return None, "unknown"
    if code == 0:
        return "Clear", "sun"
    if code == 1:
        return "Mainly clear", "sun"
    if code == 2:
        return "Partly cloudy", "partly_cloudy"
    if code == 3:
        return "Overcast", "cloud"
    if code in {45, 48}:
        return "Fog", "fog"
    if code in {51, 53, 55, 56, 57}:
        return "Drizzle", "drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "Rain", "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "Snow", "snow"
    if code in {95, 96, 99}:
        return "Thunderstorm", "thunderstorm"
    return None, "unknown"


def assess_weather_risk(activity: dict[str, Any], scheduled: dict[str, Any], *,
                        retrieved_at: str, provider: str = "open-meteo") -> dict[str, Any]:
    values = scheduled.get("values", {})
    category = (activity.get("category") or activity.get("catalog_category") or "").lower()
    tags = activity.get("raw_tags") or {}
    outdoors = any(word in category for word in ("park", "garden", "viewpoint", "beach", "outdoor", "nature", "sport"))
    outdoors = outdoors or any(str(tags.get(key, "")).lower() in {"yes", "park", "garden", "nature_reserve"}
                               for key in ("leisure", "natural", "outdoor"))
    indoor = "museum" in category or "indoor" in category or str(tags.get("tourism", "")).lower() == "museum" or str(tags.get("indoor", "")).lower() == "yes"
    rain_threshold = float(os.getenv("WEATHER_RAIN_PROBABILITY_THRESHOLD", "60"))
    heat_threshold = float(os.getenv("WEATHER_HEAT_C_THRESHOLD", "38"))
    cold_threshold = float(os.getenv("WEATHER_COLD_C_THRESHOLD", "5"))
    wind_threshold = float(os.getenv("WEATHER_WIND_KMH_THRESHOLD", "50"))
    components: list[tuple[str, float, str]] = []
    probability = values.get("precipitation_probability")
    precipitation = values.get("precipitation")
    if outdoors and probability is not None and probability >= rain_threshold:
        components.append(("rain", min(1.0, probability / 100), f"Precipitation probability is {probability}% at the scheduled hour."))
    if outdoors and precipitation is not None and precipitation >= float(os.getenv("WEATHER_RAIN_MM_THRESHOLD", "2.5")):
        components.append(("precipitation", min(1.0, precipitation / 10), f"Forecast precipitation is {precipitation} mm."))
    temp = values.get("apparent_temperature")
    if temp is None:
        temp = values.get("temperature_2m")
    if outdoors and temp is not None and (temp >= heat_threshold or temp <= cold_threshold):
        components.append(("temperature", min(1.0, abs(temp - 22) / 30), f"Apparent temperature is {temp}°C."))
    wind = values.get("wind_speed_10m")
    if outdoors and wind is not None and wind >= wind_threshold:
        components.append(("wind", min(1.0, wind / 100), f"Wind speed is {wind} km/h."))
    code = values.get("weather_code")
    condition, condition_kind = _condition(code)
    if outdoors and code is not None and code >= 95:
        components.append(("weather_condition", 0.85, f"Forecast weather code {code} indicates a thunderstorm condition."))
    present = [name for name, value in values.items() if value is not None]
    exposure_known = outdoors or indoor
    coverage_complete = (
        probability is not None
        and precipitation is not None
        and (values.get("temperature_2m") is not None or values.get("apparent_temperature") is not None)
        and wind is not None
        and code is not None
    )
    complete_assessment = bool(present) and exposure_known and coverage_complete
    advisory_score = (
        min(1.0, max((item[1] for item in components), default=0.0))
        if components
        else 0.0 if bool(present) and exposure_known and coverage_complete else None
    )
    known = complete_assessment
    score = advisory_score if known else None
    explanations = [item[2] for item in components]
    if not explanations and known:
        explanations.append("Available forecast values did not cross the configured weather advisory thresholds.")
    if indoor and components:
        explanations.append("This indoor-coded activity may be less exposed; verify venue-specific conditions.")
        advisory_score = advisory_score * 0.35 if advisory_score is not None else None
        score = score * 0.35 if score is not None else None
    level = (
        "high" if score >= 0.65 else "moderate" if score >= 0.35 else "low"
    ) if score is not None else "unavailable"
    return {
        "known": known, "score": round(score, 3) if score is not None else None,
        "advisory_score": round(advisory_score, 3) if advisory_score is not None else None,
        "level": level, "risk_dimension": "weather", "provider": provider,
        "data_kind": "forecast", "forecast_time": scheduled.get("forecast_time"),
        "retrieved_at": retrieved_at, "assessed_at": datetime.now(timezone.utc).isoformat(),
        "confidence": "forecast" if known else "partial" if present else "unavailable",
        "variables": {key: value for key, value in values.items() if value is not None},
        "condition": condition,
        "condition_kind": condition_kind,
        "advisories": [{"type": kind, "description": description, "score": round(value, 3)}
                       for kind, value, description in components],
        "explanation": explanations or (["Weather data or a defensible indoor/outdoor category is unavailable for this scheduled activity."] if not known else []),
        "outdoor_suitability_assumed": outdoors and not indoor,
    }
