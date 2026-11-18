from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Sequence


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 45
MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.5


class AssistantProviderError(Exception):
    """Base class for safe, user-facing assistant provider failures."""


class AssistantNotConfigured(AssistantProviderError):
    pass


class AssistantRateLimited(AssistantProviderError):
    pass


class AssistantTimedOut(AssistantProviderError):
    pass


class AssistantInvalidResponse(AssistantProviderError):
    pass


class AssistantUnavailable(AssistantProviderError):
    pass


def _load_sdk():
    from google import genai
    from google.genai import errors, types

    return genai, errors, types


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "code", None)
    if code is None:
        code = getattr(exc, "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


async def generate_gemini_reply(
    *,
    system_instruction: str,
    history: Sequence[tuple[str, str]],
    message: str,
) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise AssistantNotConfigured

    try:
        genai, errors, types = _load_sdk()
    except ImportError as exc:
        raise AssistantUnavailable from exc

    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    contents = [
        {
            "role": "user" if item_role == "user" else "model",
            "parts": [{"text": content}],
        }
        for item_role, content in history
    ]
    contents.append({"role": "user", "parts": [{"text": message}]})

    client = None
    async_client = None
    started = time.monotonic()
    retry_attempted = False
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_SECONDS * 1_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        async_client = client.aio
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await asyncio.wait_for(
                    async_client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            max_output_tokens=512,
                        ),
                    ),
                    timeout=REQUEST_TIMEOUT_SECONDS + 1,
                )
                logger.info(
                    "Gemini assistant provider=%s model=%s category=success duration_ms=%s "
                    "status_code=none retry_attempted=%s",
                    "gemini", model, round((time.monotonic() - started) * 1_000), retry_attempted,
                )
                break
            except asyncio.TimeoutError as exc:
                duration_ms = round((time.monotonic() - started) * 1_000)
                logger.warning(
                    "Gemini assistant provider=%s model=%s category=timeout duration_ms=%s "
                    "status_code=none retry_attempted=%s",
                    "gemini", model, duration_ms, retry_attempted,
                )
                raise AssistantTimedOut from exc
            except errors.APIError as exc:
                code = _status_code(exc)
                duration_ms = round((time.monotonic() - started) * 1_000)
                if code == 429:
                    logger.warning(
                        "Gemini assistant provider=%s model=%s category=rate_limited "
                        "duration_ms=%s status_code=%s retry_attempted=%s",
                        "gemini", model, duration_ms, code, retry_attempted,
                    )
                    raise AssistantRateLimited from exc
                if code in {401, 403}:
                    logger.warning(
                        "Gemini assistant provider=%s model=%s category=authentication "
                        "duration_ms=%s status_code=%s retry_attempted=%s",
                        "gemini", model, duration_ms, code, retry_attempted,
                    )
                    raise AssistantNotConfigured from exc
                if code in {500, 502, 503, 504} and attempt + 1 < MAX_ATTEMPTS:
                    retry_attempted = True
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
                    continue
                logger.warning(
                    "Gemini assistant provider=%s model=%s category=%s duration_ms=%s "
                    "status_code=%s retry_attempted=%s",
                    "gemini", model, "provider_error", duration_ms,
                    code if code is not None else "none", retry_attempted,
                )
                raise AssistantUnavailable from exc
            except AssistantProviderError:
                raise
            except Exception as exc:
                duration_ms = round((time.monotonic() - started) * 1_000)
                if "timeout" in type(exc).__name__.lower():
                    logger.warning(
                        "Gemini assistant provider=%s model=%s category=timeout "
                        "duration_ms=%s status_code=none retry_attempted=%s",
                        "gemini", model, duration_ms, retry_attempted,
                    )
                    raise AssistantTimedOut from exc
                if attempt + 1 < MAX_ATTEMPTS:
                    retry_attempted = True
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
                    continue
                logger.warning(
                    "Gemini assistant provider=%s model=%s category=transport_error "
                    "duration_ms=%s status_code=none retry_attempted=%s",
                    "gemini", model, duration_ms, retry_attempted,
                )
                raise AssistantUnavailable from exc
        else:  # pragma: no cover - loop exits by response or mapped exception
            raise AssistantUnavailable
    finally:
        if async_client is not None:
            try:
                await async_client.aclose()
            except Exception:
                logger.warning("Gemini assistant client cleanup failed")
        elif client is not None:
            try:
                client.close()
            except Exception:
                logger.warning("Gemini assistant client cleanup failed")

    try:
        text = getattr(response, "text", None)
    except Exception as exc:
        logger.warning(
            "Gemini assistant provider=%s model=%s category=invalid_response duration_ms=%s "
            "status_code=none retry_attempted=%s",
            "gemini", model, round((time.monotonic() - started) * 1_000), retry_attempted,
        )
        raise AssistantInvalidResponse from exc
    if not isinstance(text, str) or not text.strip():
        logger.warning(
            "Gemini assistant provider=%s model=%s category=invalid_response duration_ms=%s "
            "status_code=none retry_attempted=%s",
            "gemini", model, round((time.monotonic() - started) * 1_000), retry_attempted,
        )
        raise AssistantInvalidResponse
    return text.strip()[:1_600]
