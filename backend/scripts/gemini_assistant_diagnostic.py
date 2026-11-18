"""Run the production Gemini provider through three credential-safe probes.

Run from ``backend`` with ``python scripts/gemini_assistant_diagnostic.py``.
The cases use the normal GEMINI_API_KEY/GEMINI_MODEL settings and never print
the key, prompts, trip context, or model response text.
"""

from __future__ import annotations

import asyncio
import argparse
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")

from app.services.assistant import assistant_service  # noqa: E402
from app.services.assistant.gemini_provider import (  # noqa: E402
    AssistantProviderError,
    generate_gemini_reply,
)
from app.services.assistant.prompts import INTENT_INSTRUCTION, SYSTEM_INSTRUCTION  # noqa: E402
from app.services.assistant.schemas import (  # noqa: E402
    AssistantIntentOutput,
    assistant_intent_response_json_schema,
)


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def _mock_trip():
    """A fake saved trip with no real traveler or location-specific details."""
    return SimpleNamespace(
        id=1,
        name="Diagnostic trip",
        origin="Origin City",
        destination="Destination City",
        start_date=date(2030, 5, 1),
        end_date=date(2030, 5, 3),
        budget=10000,
        planning_options={"traveler_count": 1, "transportation_mode": "public"},
        preferences={"travel_pace": 0.5, "interests": {}},
        planning_inputs=None,
        latest_itinerary={"days": [], "budget_estimate": None},
        completed_attraction_ids=[],
        accommodation_selection=None,
        itinerary_revision=1,
        itinerary_stale=False,
    )


async def _run_case(name: str, operation) -> bool:
    started = time.monotonic()
    try:
        await operation()
        status = "success"
        error = "none"
    except AssistantProviderError as exc:
        status = "failure"
        error = type(exc).__name__
    except Exception as exc:  # Do not print exception strings or request data.
        status = "failure"
        error = type(exc).__name__
    duration_ms = round((time.monotonic() - started) * 1_000)
    print(f"diagnostic_case={name} result={status} error_class={error} duration_ms={duration_ms}")
    return status == "success"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run sanitized live Gemini provider probes.")
    parser.add_argument("--start-at", choices=("A", "B", "C"), default="A")
    parser.add_argument("--case", choices=("A", "B", "C"), help="Run only one case.")
    args = parser.parse_args()
    if not os.getenv("GEMINI_API_KEY", "").strip():
        print("diagnostic=not_run reason=GEMINI_API_KEY_not_configured")
        return 2

    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    print(f"provider=production_gemini_provider model={model}")

    async def minimal():
        response = await generate_gemini_reply(
            system_instruction="",
            history=[],
            message="Reply with exactly: Hello",
        )
        if response.strip() != "Hello":
            raise ValueError("The minimal prompt did not return the expected text.")

    async def structured():
        raw = await generate_gemini_reply(
            system_instruction=SYSTEM_INSTRUCTION + INTENT_INSTRUCTION,
            history=[],
            message="Please make the trip more relaxed.",
            response_json_schema=assistant_intent_response_json_schema(),
        )
        AssistantIntentOutput.model_validate_json(raw)

    async def with_mock_trip_context():
        await assistant_service.process_assistant_message(
            db=None,
            user_id=0,
            message="What destination is this saved trip for?",
            conversation_history=[],
            trip=_mock_trip(),
        )

    cases = {
        "A": ("A_minimal_provider", minimal),
        "B": ("B_structured_intent", structured),
        "C": ("C_mock_trip_context", with_mock_trip_context),
    }
    selected = [cases[args.case]] if args.case else [
        cases[key] for key in ("A", "B", "C") if key >= args.start_at
    ]
    outcomes = [await _run_case(name, operation) for name, operation in selected]
    return 0 if all(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
