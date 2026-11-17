"""Server-side, multi-page PDF export for the currently persisted itinerary."""

from __future__ import annotations

from io import BytesIO
import re
import textwrap
from typing import Any

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from app.services.weather import ATTRIBUTION as WEATHER_ATTRIBUTION


PAGE_SIZE = (8.27, 11.69)  # A4, inches
LINE_HEIGHT = 0.027
BODY_WIDTH = 96


def _inr(value: Any) -> str:
    if value is None:
        return "Unavailable"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    return f"₹{amount:,.0f}"


def _clock(value: Any) -> str:
    try:
        minute = int(value)
    except (TypeError, ValueError):
        return "Time unavailable"
    return f"{minute // 60 % 24:02d}:{minute % 60:02d}"


def _safe_filename(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-_")
    return (slug[:70] or "gowander-itinerary") + ".pdf"


def _wrapped_lines(text: str) -> list[str]:
    return textwrap.wrap(
        str(text), width=BODY_WIDTH, break_long_words=True, break_on_hyphens=True,
    ) or [""]


def _document_lines(trip: Any) -> list[tuple[str, str]]:
    itinerary = trip.latest_itinerary if isinstance(trip.latest_itinerary, dict) else {}
    options = trip.planning_options if isinstance(trip.planning_options, dict) else {}
    lines: list[tuple[str, str]] = [
        ("title", str(trip.name or trip.destination or "Travel itinerary")),
        ("subhead", str(trip.destination or "Destination unavailable")),
    ]
    details = [f"Dates: {trip.start_date} to {trip.end_date}"]
    if trip.origin:
        details.insert(0, f"Starting city: {trip.origin}")
    if options.get("traveler_count") is not None:
        details.append(f"Travelers: {options['traveler_count']}")
    lines.extend(("body", detail) for detail in details)
    lines.append(("space", ""))
    lines.append(("section", "Daily itinerary"))

    days = itinerary.get("days") if isinstance(itinerary.get("days"), list) else []
    planning = trip.planning_inputs if isinstance(trip.planning_inputs, dict) else {}
    attraction_fees = {
        item.get("id"): item.get("cost_known")
        for item in planning.get("attractions", [])
        if isinstance(item, dict) and item.get("id")
    }
    for day in days:
        if not isinstance(day, dict):
            continue
        day_number = day.get("day_number", "?")
        lines.append(("day", f"Day {day_number} · {day.get('date', '')}".strip(" ·")))
        lines.append((
            "body",
            f"Estimated travel: {int(day.get('total_travel_minutes') or 0)} min · "
            f"Meal/rest time: {int(day.get('reserved_break_minutes') or 0)} min",
        ))
        entries: list[tuple[int, str, dict[str, Any]]] = []
        for stop in day.get("stops", []) or []:
            if not isinstance(stop, dict):
                continue
            entries.append((int(stop.get("arrival_minute") or 0), "stop", stop))
        for meal in day.get("meal_breaks", []) or []:
            if isinstance(meal, dict):
                entries.append((int(meal.get("start_minute") or 0), "meal", meal))
        for _, entry_type, entry in sorted(entries, key=lambda value: value[0]):
            if entry_type == "meal":
                start = int(entry.get("start_minute") or 0)
                duration = int(entry.get("duration_minutes") or 0)
                lines.append(("bullet", f"{_clock(start)}–{_clock(start + duration)} · Meal/rest break · {duration} min"))
                continue
            arrival = int(entry.get("arrival_minute") or 0)
            departure = int(entry.get("departure_minute") or arrival)
            duration = max(0, departure - arrival)
            fee_known = attraction_fees.get(entry.get("attraction_id"))
            fee_value = entry.get("cost")
            fee = _inr(fee_value) if fee_known is True and fee_value is not None else "Fee unknown"
            lines.append((
                "bullet",
                f"{_clock(arrival)}–{_clock(departure)} · {entry.get('name') or 'Activity'} · "
                f"Visit {duration} min · Travel before {int(entry.get('travel_minutes_before') or 0)} min · {fee}",
            ))
            assessment = entry.get("weather_assessment")
            if isinstance(assessment, dict):
                advisories = assessment.get("advisories") or []
                for advisory in advisories:
                    if isinstance(advisory, dict) and advisory.get("description"):
                        condition = assessment.get("condition") or "Forecast condition"
                        forecast_time = assessment.get("forecast_time")
                        when = f" at {forecast_time}" if forecast_time else ""
                        lines.append((
                            "weather",
                            f"Weather advisory for {entry.get('name') or 'activity'}{when}: "
                            f"{condition}. {advisory.get('description')}",
                        ))

    estimate = itinerary.get("budget_estimate")
    if isinstance(estimate, dict):
        lines.extend([("space", ""), ("section", "Estimated destination expenses")])
        for category in estimate.get("categories", []) or []:
            if isinstance(category, dict):
                label = category.get("label") or category.get("key") or "Expense"
                amount = category.get("amount", category.get("estimated_amount", 0))
                lines.append(("body", f"{label}: {_inr(amount)}"))
                for assumption in category.get("assumptions", []) or []:
                    lines.append(("small", f"Assumption: {assumption}"))
        lines.append(("body", f"Total estimated: {_inr(estimate.get('total_estimated', 0))}"))
        for exclusion in estimate.get("exclusions", []) or []:
            lines.append(("small", f"Excluded: {exclusion}"))

    source_attributions = list(dict.fromkeys(
        item.get("attribution")
        for item in planning.get("attractions", [])
        if isinstance(item, dict) and item.get("attribution")
    ))
    has_osm = any(
        isinstance(item, dict)
        and (item.get("data_source") == "osm" or item.get("provider_name") == "openstreetmap")
        for item in planning.get("attractions", [])
    )
    if source_attributions or has_osm:
        lines.extend([("space", ""), ("section", "Attribution")])
        lines.extend(("small", attribution) for attribution in source_attributions)
        if has_osm and not source_attributions:
            lines.append(("small", "© OpenStreetMap contributors · Open Database License (ODbL)"))
    if any(
        isinstance(stop, dict) and isinstance(stop.get("weather_assessment"), dict)
        for day in days if isinstance(day, dict)
        for stop in day.get("stops", []) or []
    ):
        lines.append(("small", WEATHER_ATTRIBUTION))
    lines.extend([
        ("space", ""),
        ("small", "Times and expenses are estimates. Confirm venue details and costs before travel."),
    ])
    return lines


def render_itinerary_pdf(trip: Any) -> bytes:
    """Render a printable A4 PDF from the trip's latest database snapshot."""
    content = _document_lines(trip)
    pages: list[list[tuple[str, str]]] = [[]]
    used = 0
    max_lines = 30
    for kind, text in content:
        wrapped = [(kind, line) for line in _wrapped_lines(text)] if kind != "space" else [(kind, "")]
        if kind in {"section", "day"} and used > max_lines - 4:
            pages.append([])
            used = 0
        for wrapped_item in wrapped:
            if used >= max_lines:
                pages.append([])
                used = 0
            pages[-1].append(wrapped_item)
            used += 1
    if not pages[-1]:
        pages.pop()

    buffer = BytesIO()
    title = str(trip.name or trip.destination or "GoWander itinerary")
    with PdfPages(buffer, metadata={"Title": title, "Author": "GoWander"}) as pdf:
        for page_number, page_lines in enumerate(pages, start=1):
            figure = Figure(figsize=PAGE_SIZE, facecolor="white")
            figure.text(0.075, 0.965, "GoWander", fontsize=9, color="#27766f", weight="bold", parse_math=False)
            figure.text(0.925, 0.965, "TRAVEL ITINERARY", fontsize=8, color="#68747c", ha="right", parse_math=False)
            figure.add_artist(Line2D(
                [0.075, 0.925], [0.948, 0.948], transform=figure.transFigure,
                color="#dce5e3", linewidth=0.8,
            ))
            y = 0.918
            for kind, text in page_lines:
                if kind == "space":
                    y -= LINE_HEIGHT / 2
                    continue
                style = {
                    "title": (17, "#182b32", "bold", 0.036),
                    "subhead": (11, "#27766f", "bold", 0.032),
                    "section": (12, "#182b32", "bold", 0.032),
                    "day": (10, "#27766f", "bold", 0.030),
                    "body": (8.5, "#293940", "normal", LINE_HEIGHT),
                    "bullet": (8.2, "#293940", "normal", LINE_HEIGHT),
                    "weather": (8, "#73551a", "normal", LINE_HEIGHT),
                    "small": (7.5, "#596970", "normal", LINE_HEIGHT),
                }.get(kind, (8.5, "#293940", "normal", LINE_HEIGHT))
                size, color, weight, decrement = style
                prefix = "• " if kind in {"bullet", "weather"} else ""
                figure.text(
                    0.09 if kind in {"bullet", "weather", "small"} else 0.075,
                    y,
                    prefix + text,
                    fontsize=size,
                    color=color,
                    weight=weight,
                    va="top",
                    parse_math=False,
                )
                y -= decrement
            figure.text(
                0.925, 0.035, f"GoWander · Page {page_number} of {len(pages)}",
                fontsize=7, color="#68747c", ha="right", parse_math=False,
            )
            pdf.savefig(figure)
            figure.clear()
    return buffer.getvalue()


def itinerary_pdf_filename(trip: Any) -> str:
    return _safe_filename(str(trip.name or trip.destination or "GoWander itinerary"))
