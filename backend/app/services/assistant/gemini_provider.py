from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Sequence
from typing import Any


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 18
TOTAL_REQUEST_TIMEOUT_SECONDS = 25
CLIENT_CLEANUP_TIMEOUT_SECONDS = 1
MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.25
RETRYABLE_TRANSPORT_EXCEPTIONS = {
    "ConnectError",
    "ConnectTimeout",
    "NetworkError",
    "PoolTimeout",
    "ProxyError",
    "ReadError",
    "ReadTimeout",
    "RemoteProtocolError",
    "WriteError",
    "WriteTimeout",
}


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


def create_gemini_client(api_key: str):
    """Build the shared async Gemini client used by the app and diagnostic scripts."""
    genai, errors, types = _load_sdk()
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_SECONDS * 1_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    return client, errors, types


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "code", None)
    if code is None:
        code = getattr(exc, "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def _safe_exception_message(exc: Exception, *, api_key: str, request_text: Sequence[str]) -> str:
    """Sanitize SDK errors before logging; never include secrets or request fields."""
    message = str(exc)
    for sensitive in (api_key, *request_text):
        if sensitive:
            message = re.sub(re.escape(sensitive), "[redacted]", message, flags=re.IGNORECASE)
    message = re.sub(r"(?i)AIza[0-9A-Za-z_-]{20,}", "[redacted-key]", message)
    message = re.sub(
        r"(?i)(authorization|x-goog-api-key|api[_-]?key)(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[redacted]",
        message,
    )
    message = re.sub(r"https?://[^\s\"'<>]+", "[redacted-url]", message)
    message = re.sub(r"[\r\n\t]+", " ", message)
    return message[:240] if message else "<empty exception message>"


def _is_retryable_transport_error(exc: Exception) -> bool:
    return type(exc).__name__ in RETRYABLE_TRANSPORT_EXCEPTIONS or isinstance(exc, ConnectionError)


async def generate_gemini_reply(
    *,
    system_instruction: str,
    history: Sequence[tuple[str, str]],
    message: str,
    response_json_schema: dict[str, Any] | None = None,
) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise AssistantNotConfigured

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
    deadline = started + TOTAL_REQUEST_TIMEOUT_SECONDS
    retry_attempted = False
    request_text = [system_instruction, message, *(content for _role, content in history)]
    generation_config: dict[str, Any] = {
        "max_output_tokens": 512,
    }
    if system_instruction:
        generation_config["system_instruction"] = system_instruction
    if response_json_schema is not None:
        generation_config.update({
            "response_mime_type": "application/json",
            "response_json_schema": response_json_schema,
        })
    try:
        client, errors, types = create_gemini_client(api_key)
        async_client = client.aio
    except Exception as exc:
        logger.warning(
            "Gemini assistant provider=%s model=%s category=client_initialization_error "
            "stage=client_initialization exception_class=%s exception_message=%r "
            "duration_ms=%s request_attempt=none retry_attempted=false status_code=%s",
            "gemini", model, type(exc).__name__,
            _safe_exception_message(exc, api_key=api_key, request_text=request_text),
            round((time.monotonic() - started) * 1_000), _status_code(exc) or "none",
        )
        raise AssistantUnavailable from exc

    try:
        for attempt in range(MAX_ATTEMPTS):
            request_attempt = "initial" if attempt == 0 else "retry"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "Gemini assistant provider=%s model=%s category=timeout stage=request_execution "
                    "exception_class=TotalRequestDeadline exception_message=deadline_exhausted "
                    "duration_ms=%s request_attempt=%s status_code=none retry_attempted=%s",
                    "gemini", model, round((time.monotonic() - started) * 1_000),
                    request_attempt, retry_attempted,
                )
                raise AssistantTimedOut
            try:
                response = await asyncio.wait_for(
                    async_client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(**generation_config),
                    ),
                    timeout=min(REQUEST_TIMEOUT_SECONDS, remaining),
                )
                logger.info(
                    "Gemini assistant provider=%s model=%s category=success stage=request_execution "
                    "duration_ms=%s request_attempt=%s status_code=none retry_attempted=%s",
                    "gemini", model, round((time.monotonic() - started) * 1_000), request_attempt, retry_attempted,
                )
                break
            except asyncio.TimeoutError as exc:
                duration_ms = round((time.monotonic() - started) * 1_000)
                logger.warning(
                    "Gemini assistant provider=%s model=%s category=timeout stage=request_execution "
                    "exception_class=%s exception_message=%r duration_ms=%s request_attempt=%s "
                    "status_code=none retry_attempted=%s",
                    "gemini", model, type(exc).__name__,
                    _safe_exception_message(exc, api_key=api_key, request_text=request_text),
                    duration_ms, request_attempt, retry_attempted,
                )
                raise AssistantTimedOut from exc
            except errors.APIError as exc:
                code = _status_code(exc)
                duration_ms = round((time.monotonic() - started) * 1_000)
                logger.warning(
                    "Gemini assistant provider=%s model=%s category=provider_response_error "
                    "stage=request_execution exception_class=%s exception_message=%r duration_ms=%s "
                    "request_attempt=%s status_code=%s retry_attempted=%s",
                    "gemini", model, type(exc).__name__,
                    _safe_exception_message(exc, api_key=api_key, request_text=request_text),
                    duration_ms, request_attempt, code if code is not None else "none", retry_attempted,
                )
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
                if code == 504:
                    raise AssistantTimedOut from exc
                if code in {500, 502} and attempt + 1 < MAX_ATTEMPTS:
                    remaining = deadline - time.monotonic()
                    if remaining <= RETRY_BACKOFF_SECONDS:
                        raise AssistantTimedOut from exc
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
                        "Gemini assistant provider=%s model=%s category=timeout stage=request_execution "
                        "exception_class=%s exception_message=%r duration_ms=%s request_attempt=%s "
                        "status_code=none retry_attempted=%s",
                        "gemini", model, type(exc).__name__,
                        _safe_exception_message(exc, api_key=api_key, request_text=request_text),
                        duration_ms, request_attempt, retry_attempted,
                    )
                    raise AssistantTimedOut from exc
                retryable_transport = _is_retryable_transport_error(exc)
                remaining = deadline - time.monotonic()
                if retryable_transport and attempt + 1 < MAX_ATTEMPTS and remaining > RETRY_BACKOFF_SECONDS:
                    logger.warning(
                        "Gemini assistant provider=%s model=%s category=transport_retry stage=request_execution "
                        "exception_class=%s exception_message=%r duration_ms=%s request_attempt=%s "
                        "status_code=none retry_attempted=true",
                        "gemini", model, type(exc).__name__,
                        _safe_exception_message(exc, api_key=api_key, request_text=request_text),
                        duration_ms, request_attempt,
                    )
                    retry_attempted = True
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
                    continue
                logger.warning(
                    "Gemini assistant provider=%s model=%s category=%s stage=request_execution "
                    "exception_class=%s exception_message=%r duration_ms=%s request_attempt=%s "
                    "status_code=none retry_attempted=%s",
                    "gemini", model, "transport_error" if retryable_transport else "request_error", type(exc).__name__,
                    _safe_exception_message(exc, api_key=api_key, request_text=request_text),
                    duration_ms, request_attempt, retry_attempted,
                )
                raise AssistantUnavailable from exc
        else:  # pragma: no cover - loop exits by response or mapped exception
            raise AssistantUnavailable
    finally:
        if async_client is not None:
            try:
                await asyncio.wait_for(
                    async_client.aclose(), timeout=CLIENT_CLEANUP_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                logger.warning("Gemini assistant client cleanup timed out")
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
