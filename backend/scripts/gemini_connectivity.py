"""One-request, credential-safe connectivity probe for a Gemini model.

Run from ``backend`` with ``python scripts/gemini_connectivity.py [MODEL]``.
The positional model overrides GEMINI_MODEL; otherwise GEMINI_MODEL is used.
The script loads backend/.env without printing its contents and never retries.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _error_category(status_code: int | None) -> tuple[str, str]:
    if status_code == 401:
        return "authentication", "API returned HTTP 401"
    if status_code == 403:
        return "project_tier_or_permission", "API returned HTTP 403; model access denied for this key/project"
    if status_code == 404:
        return "model_unavailable", "API returned HTTP 404; model or generateContent endpoint unavailable"
    if status_code == 429:
        return "rate_limited", "API returned HTTP 429"
    if status_code in {500, 502, 503, 504}:
        return "provider_unavailable", f"API returned HTTP {status_code}"
    if status_code is not None:
        return "provider_error", f"API returned HTTP {status_code}"
    return "transport_error", "No HTTP status received; transport failed"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Send exactly one minimal Gemini API request.")
    parser.add_argument(
        "model",
        nargs="?",
        default=None,
        help="Model ID (overrides GEMINI_MODEL)",
    )
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = (args.model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")).strip()
    if not api_key:
        print(
            f"model={model or 'unset'} http_status=none success=false "
            "error_category=missing_configuration request_duration_ms=0 "
            "provider_error=GEMINI_API_KEY_not_configured"
        )
        return 2
    if not model:
        print(
            "model=unset http_status=none success=false error_category=missing_configuration "
            "request_duration_ms=0 provider_error=GEMINI_MODEL_not_configured"
        )
        return 2

    from google import genai
    from google.genai import errors, types

    timeout_seconds = 45
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=timeout_seconds * 1_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    started = time.monotonic()
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model,
                contents="Reply with exactly: Hello",
                config=types.GenerateContentConfig(max_output_tokens=16),
            ),
            timeout=timeout_seconds + 1,
        )
        duration_ms = round((time.monotonic() - started) * 1_000)
        response_text = getattr(response, "text", None)
        if isinstance(response_text, str) and response_text.strip():
            print(
                f"model={model} http_status=200 success=true error_category=none "
                f"request_duration_ms={duration_ms} provider_error=none response={response_text.strip()}"
            )
            return 0
        print(
            f"model={model} http_status=200 success=false error_category=empty_response "
            f"request_duration_ms={duration_ms} provider_error=HTTP_200_empty_text_response"
        )
        return 1
    except errors.APIError as exc:
        duration_ms = round((time.monotonic() - started) * 1_000)
        code = getattr(exc, "code", None)
        status_code = code if isinstance(code, int) else None
        category, safe_error = _error_category(status_code)
        print(
            f"model={model} http_status={status_code if status_code is not None else 'none'} "
            f"success=false error_category={category} request_duration_ms={duration_ms} "
            f"provider_error={safe_error.replace(' ', '_').replace(';', ',')}"
        )
        return 1
    except Exception as exc:
        duration_ms = round((time.monotonic() - started) * 1_000)
        if "timeout" in type(exc).__name__.lower():
            category, safe_error = "timeout", "request_timeout_without_HTTP_status"
        else:
            category, safe_error = "transport_error", f"transport_exception_{type(exc).__name__}"
        print(
            f"model={model} http_status=none success=false error_category={category} "
            f"request_duration_ms={duration_ms} provider_error={safe_error}"
        )
        return 1
    finally:
        await client.aio.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
