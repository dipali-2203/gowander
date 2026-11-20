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
    selection = getattr(trip, "accommodation_selection", None)
    selected_hotel = getattr(selection, "hotel", None) if selection is not None else None
    if selected_hotel is not None:
        lines.extend([("section", "Selected accommodation"),
                      ("body", f"{selected_hotel.name} ({selected_hotel.hotel_type.replace('_', ' ')})")])
        if selected_hotel.nightly_price is not None:
            lines.append(("body", f"Listed price: {_inr(selected_hotel.nightly_price)} per room per night; {selected_hotel.price_source or 'source listing'}, not a booking quote."))
        else:
            lines.append(("body", "Nightly price unavailable; the budget retains its configured accommodation allowance."))
        if selected_hotel.address:
            lines.append(("body", selected_hotel.address))
        if selected_hotel.attribution:
            lines.append(("small", selected_hotel.attribution))
        if selected_hotel.source_dataset:
            lines.append(("small", f"Source dataset: {selected_hotel.source_dataset}"))
        lines.append(("space", ""))
    lines.append(("section", "Daily itinerary"))

    days = itinerary.get("days") if isinstance(itinerary.get("days"), list) else []
    planning = trip.planning_inputs if isinstance(trip.planning_inputs, dict) else {}
    estimate = itinerary.get("budget_estimate")
    has_fee_details = isinstance(estimate, dict) and isinstance(estimate.get("attraction_fee_details"), list)
    attraction_fee_details = {
        item.get("attraction_id"): item
        for item in (estimate.get("attraction_fee_details", []) if isinstance(estimate, dict) else [])
        if isinstance(item, dict) and item.get("attraction_id")
    }
    legacy_fee_known = {
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
            fee_detail = attraction_fee_details.get(entry.get("attraction_id"), {})
            if fee_detail.get("status") == "verified" and isinstance(fee_detail.get("representative"), (int, float)):
                fee = f"Verified fee {_inr(fee_detail['representative'])}"
            elif fee_detail.get("status") == "estimated" and isinstance(fee_detail.get("representative"), (int, float)):
                fee = f"Estimated fee allowance {_inr(fee_detail['representative'])} (not verified)"
            elif (
                not has_fee_details
                and legacy_fee_known.get(entry.get("attraction_id")) is True
                and entry.get("cost") is not None
            ):
                fee = f"Fee {_inr(entry['cost'])} (legacy saved estimate)"
            else:
                fee = "Fee unavailable"
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

    if isinstance(estimate, dict) and isinstance(estimate.get("daily_attraction_fees"), list):
        lines.extend([("space", ""), ("section", "Daily attraction fee estimates")])
        for fee_day in estimate["daily_attraction_fees"]:
            if not isinstance(fee_day, dict):
                continue
            day_label = f"Day {fee_day.get('day_number', '?')} · {fee_day.get('date', '')}".strip(" ·")
            if fee_day.get("status") == "no_attractions":
                summary = "No attractions scheduled."
            elif fee_day.get("status") == "already_counted":
                summary = "Repeated attraction fee(s) were counted on their first scheduled day."
            elif fee_day.get("status") == "unavailable":
                summary = f"Fee estimate unavailable for {fee_day.get('unresolved_attraction_count', 0)} attraction(s)."
            else:
                verified = fee_day.get("verified_fee_total")
                estimated = fee_day.get("estimated_fee_representative_total")
                summary = f"Verified: {_inr(verified)} · Estimated: {_inr(estimated)} (not verified)"
                if fee_day.get("status") == "partial":
                    summary += f" · {fee_day.get('unresolved_attraction_count', 0)} unresolved"
            lines.append(("body", f"{day_label}: {summary}"))
            if isinstance(fee_day.get("estimated_fee_lower_total"), (int, float)) and isinstance(fee_day.get("estimated_fee_upper_total"), (int, float)):
                lines.append(("small", f"Estimated fee range: {_inr(fee_day['estimated_fee_lower_total'])}–{_inr(fee_day['estimated_fee_upper_total'])}"))
        lines.append(("small", "Daily fees use the same backend estimate as the complete budget; they exclude other trip expenses."))

    if isinstance(estimate, dict):
        complete = estimate.get("complete_budget")
        is_stale = bool(getattr(trip, "itinerary_stale", False))
        complete_is_current = isinstance(complete, dict) and not is_stale
        lines.extend([("space", ""), ("section", "Complete trip budget" if complete_is_current else "Trip budget estimate")])
        if is_stale:
            lines.append(("body", "This estimate is out of date because trip details changed. Regenerate the itinerary for a current estimate."))
        elif complete_is_current and isinstance(complete, dict):
            lines.append(("small", f"Completeness: {complete.get('completeness') or 'incomplete'}"))
            for category in complete.get("categories", []) or []:
                if not isinstance(category, dict):
                    continue
                label = category.get("label") or category.get("key") or "Expense"
                status = str(category.get("status") or "unavailable").replace("_", " ").title()
                amount = category.get("amount") if isinstance(category.get("amount"), (int, float)) else None
                if status == "Unavailable" or amount is None:
                    value = "Unavailable"
                elif status == "Partial":
                    has_estimate = isinstance(category.get("estimated_amount"), (int, float)) and category["estimated_amount"] > 0
                    has_verified = isinstance(category.get("verified_amount"), (int, float)) and category["verified_amount"] > 0
                    value = (f"{_inr(amount)} available estimate (partial)" if has_estimate else
                             f"{_inr(amount)} known subtotal (partial)" if has_verified or amount > 0 else
                             "Partial; no known amount")
                else:
                    value = _inr(amount)
                lines.append(("body", f"{label}: {value} ({status})"))
                if category.get("source"):
                    lines.append(("small", f"Source: {category['source']}"))
                if isinstance(category.get("range_min"), (int, float)) and isinstance(category.get("range_max"), (int, float)):
                    lines.append(("small", f"Indicative range: {_inr(category['range_min'])}–{_inr(category['range_max'])}"))
                if category.get("mode"):
                    lines.append(("small", f"Mode: {str(category['mode']).replace('_', ' ')}"))
                if category.get("unit_basis"):
                    basis = str(category["unit_basis"]).replace("_", " ")
                    travelers = category.get("traveler_count")
                    lines.append(("small", f"Pricing basis: {basis}" + (f"; {travelers} traveler(s)" if travelers else "")))
                if category.get("amount_basis"):
                    lines.append(("small", f"Amount basis: {str(category['amount_basis']).replace('_', ' ')}"))
                if isinstance(category.get("distance_km"), (int, float)):
                    lines.append(("small", f"Modeled distance: {category['distance_km']:.1f} km"))
                if category.get("estimated_at"):
                    lines.append(("small", f"Estimate created: {category['estimated_at']}"))
                for assumption in category.get("assumptions", []) or []:
                    lines.append(("small", f"Assumption: {assumption}"))
            total = complete.get("total_estimate")
            lines.append(("body", f"Complete trip total: {_inr(total)}"))
            if isinstance(complete.get("total_estimate_range_min"), (int, float)) and isinstance(complete.get("total_estimate_range_max"), (int, float)):
                lines.append(("small", f"Indicative total range: {_inr(complete['total_estimate_range_min'])}–{_inr(complete['total_estimate_range_max'])}; budget checks use the upper bounds."))
            limit = complete.get("budget_limit")
            upper = complete.get("total_estimate_range_max")
            if isinstance(limit, (int, float)) and isinstance(total, (int, float)) and total > limit:
                lines.append(("body", f"Representative estimate over budget by {_inr(total - limit)}."))
            if isinstance(limit, (int, float)) and isinstance(upper, (int, float)) and upper > limit:
                lines.append(("body", f"Upper-range estimate over budget by {_inr(upper - limit)}."))
            if total is None:
                lines.append(("small", "The budget is incomplete; unknown costs are not counted as zero."))
            elif complete.get("within_budget") is True:
                lines.append(("body", "Budget status: Within budget across the estimated ranges"))
            elif complete.get("within_budget") is False:
                limit = complete.get("budget_limit")
                upper = complete.get("total_estimate_range_max")
                overrun = upper - limit if isinstance(limit, (int, float)) and isinstance(upper, (int, float)) else None
                lines.append(("body", f"Budget status: Over the budget at the upper estimate by {_inr(max(0, overrun))}" if overrun is not None else "Budget status: Over the budget at the upper estimate"))
            else:
                lines.append(("body", "Budget feasibility cannot be fully determined."))
            for assumption in complete.get("assumptions", []) or []:
                lines.append(("small", f"Assumption: {assumption}"))
            for exclusion in complete.get("exclusions", []) or []:
                lines.append(("small", f"Excluded: {exclusion}"))
        else:
            lines.append(("small", "Legacy destination-only estimate; intercity travel is excluded."))
            for category in estimate.get("categories", []) or []:
                if isinstance(category, dict):
                    label = category.get("label") or category.get("key") or "Expense"
                    amount = category.get("amount") if isinstance(category.get("amount"), (int, float)) else None
                    lines.append(("body", f"{label}: {_inr(amount)}"))
                    for assumption in category.get("assumptions", []) or []:
                        lines.append(("small", f"Assumption: {assumption}"))
            total = estimate.get("total_estimated") if isinstance(estimate.get("total_estimated"), (int, float)) else None
            lines.append(("body", f"Destination-only total: {_inr(total)}"))
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
