# -*- coding: utf-8 -*-
"""OpenAI chat model compatibility wrappers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Type

from agentscope.model import OpenAIChatModel
from agentscope.model._model_response import ChatResponse
from openai import APIError, InternalServerError, RateLimitError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Retry configuration constants
COPAW_MODEL_RETRIES = 3
COPAW_MODEL_BACKOFF_BASE = 1.0
COPAW_MODEL_BACKOFF_CAP = 60.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _get_model_retries() -> int:
    """Get max retry count from environment variable."""
    try:
        return int(os.environ.get("COPAW_MODEL_RETRIES", COPAW_MODEL_RETRIES))
    except (ValueError, TypeError):
        return COPAW_MODEL_RETRIES


def _get_backoff_base() -> float:
    """Get base backoff delay from environment variable."""
    try:
        return float(
            os.environ.get(
                "COPAW_MODEL_BACKOFF_BASE",
                COPAW_MODEL_BACKOFF_BASE,
            ),
        )
    except (ValueError, TypeError):
        return COPAW_MODEL_BACKOFF_BASE


def _get_backoff_cap() -> float:
    """Get max backoff delay from environment variable."""
    try:
        return float(
            os.environ.get("COPAW_MODEL_BACKOFF_CAP", COPAW_MODEL_BACKOFF_CAP),
        )
    except (ValueError, TypeError):
        return COPAW_MODEL_BACKOFF_CAP


def _compute_backoff_seconds(attempt: int, base: float, cap: float) -> float:
    """Compute exponential backoff delay for the given attempt.

    Args:
        attempt: Current retry attempt (0-indexed).
        base: Base delay in seconds.
        cap: Maximum delay cap in seconds.

    Returns:
        Delay in seconds (capped at cap).
    """
    return min(cap, base * (2**attempt))


def _is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable.

    Args:
        error: The exception to check.

    Returns:
        True if the error should trigger a retry, False otherwise.
    """
    # RateLimitError and InternalServerError are always retryable
    if isinstance(error, (RateLimitError, InternalServerError)):
        return True

    # For generic APIError, check status code
    if isinstance(error, APIError):
        status_code = getattr(error, "status_code", None)
        if status_code in RETRYABLE_STATUS_CODES:
            return True

    return False


def _clone_with_overrides(obj: Any, **overrides: Any) -> Any:
    """Clone a stream object into a mutable namespace with overrides."""
    data = dict(getattr(obj, "__dict__", {}))
    data.update(overrides)
    return SimpleNamespace(**data)


def _sanitize_tool_call(tool_call: Any) -> Any | None:
    """Normalize a tool call for parser safety, or drop it if unusable."""
    if not hasattr(tool_call, "index"):
        return None

    function = getattr(tool_call, "function", None)
    if function is None:
        return None

    has_name = hasattr(function, "name")
    has_arguments = hasattr(function, "arguments")

    raw_name = getattr(function, "name", "")
    if isinstance(raw_name, str):
        safe_name = raw_name
    elif raw_name is None:
        safe_name = ""
    else:
        safe_name = str(raw_name)

    raw_arguments = getattr(function, "arguments", "")
    if isinstance(raw_arguments, str):
        safe_arguments = raw_arguments
    elif raw_arguments is None:
        safe_arguments = ""
    else:
        try:
            safe_arguments = json.dumps(raw_arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            safe_arguments = str(raw_arguments)

    if (
        has_name
        and has_arguments
        and isinstance(raw_name, str)
        and isinstance(
            raw_arguments,
            str,
        )
    ):
        return tool_call

    safe_function = SimpleNamespace(
        name=safe_name,
        arguments=safe_arguments,
    )
    return _clone_with_overrides(tool_call, function=safe_function)


def _sanitize_chunk(chunk: Any) -> Any:
    """Drop/normalize malformed tool-calls in a streaming chunk."""
    choices = getattr(chunk, "choices", None)
    if not choices:
        return chunk

    sanitized_choices: list[Any] = []
    changed = False

    for choice in choices:
        delta = getattr(choice, "delta", None)
        if delta is None:
            sanitized_choices.append(choice)
            continue

        raw_tool_calls = getattr(delta, "tool_calls", None)
        if not raw_tool_calls:
            sanitized_choices.append(choice)
            continue

        choice_changed = False
        sanitized_tool_calls: list[Any] = []
        for tool_call in raw_tool_calls:
            sanitized = _sanitize_tool_call(tool_call)
            if sanitized is not tool_call:
                choice_changed = True
            if sanitized is not None:
                sanitized_tool_calls.append(sanitized)

        if choice_changed:
            changed = True
            sanitized_delta = _clone_with_overrides(
                delta,
                tool_calls=sanitized_tool_calls,
            )
            sanitized_choice = _clone_with_overrides(
                choice,
                delta=sanitized_delta,
            )
            sanitized_choices.append(sanitized_choice)
            continue

        sanitized_choices.append(choice)

    if not changed:
        return chunk
    return _clone_with_overrides(chunk, choices=sanitized_choices)


def _sanitize_stream_item(item: Any) -> Any:
    """Sanitize either plain stream chunks or structured stream items."""
    if hasattr(item, "chunk"):
        chunk = item.chunk
        sanitized_chunk = _sanitize_chunk(chunk)
        if sanitized_chunk is chunk:
            return item
        return _clone_with_overrides(item, chunk=sanitized_chunk)

    return _sanitize_chunk(item)


class _SanitizedStream:
    """Proxy OpenAI async stream that sanitizes each emitted item and
    captures ``extra_content`` from tool-call chunks (used by Gemini
    thinking models to carry ``thought_signature``)."""

    def __init__(self, stream: Any):
        self._stream = stream
        self._ctx_stream: Any | None = None
        self.extra_contents: dict[str, Any] = {}

    async def __aenter__(self) -> "_SanitizedStream":
        self._ctx_stream = await self._stream.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        tb: Any,
    ) -> bool | None:
        return await self._stream.__aexit__(exc_type, exc, tb)

    def __aiter__(self) -> "_SanitizedStream":
        return self

    async def __anext__(self) -> Any:
        if self._ctx_stream is None:
            raise StopAsyncIteration
        item = await self._ctx_stream.__anext__()
        self._capture_extra_content(item)
        return _sanitize_stream_item(item)

    def _capture_extra_content(self, item: Any) -> None:
        """Store ``extra_content`` keyed by tool-call id."""
        chunk = getattr(item, "chunk", item)
        for choice in getattr(chunk, "choices", []):
            delta = getattr(choice, "delta", None)
            if not delta:
                continue
            for tc in getattr(delta, "tool_calls", None) or []:
                tc_id = getattr(tc, "id", None)
                if not tc_id:
                    continue
                extra = getattr(tc, "extra_content", None)
                if extra is None:
                    model_extra = getattr(tc, "model_extra", None)
                    if isinstance(model_extra, dict):
                        extra = model_extra.get("extra_content")
                if extra:
                    self.extra_contents[tc_id] = extra


class OpenAIChatModelCompat(OpenAIChatModel):
    """OpenAIChatModel with robust parsing for malformed tool-call chunks
    and transparent ``extra_content`` (Gemini thought_signature) relay."""

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the model with retry mechanism for transient errors.

        Retries on 503 (Service Unavailable), 429 (Rate Limit),
        and other transient server errors with exponential backoff.

        Args:
            *args: Positional arguments passed to parent __call__.
            **kwargs: Keyword arguments passed to parent __call__.

        Returns:
            The model response.

        Raises:
            The last error encountered if all retries are exhausted.
        """
        max_retries = _get_model_retries()
        base_delay = _get_backoff_base()
        cap_delay = _get_backoff_cap()
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return await super().__call__(*args, **kwargs)
            except (InternalServerError, RateLimitError, APIError) as e:
                last_error = e
                if not _is_retryable_error(e) or attempt >= max_retries:
                    raise

                delay = _compute_backoff_seconds(
                    attempt,
                    base_delay,
                    cap_delay,
                )
                logger.warning(
                    "Model API error (attempt %d/%d): %s. "
                    "Retrying in %.2fs...",
                    attempt + 1,
                    max_retries + 1,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)

        # This should not be reached, but just in case
        if last_error:
            raise last_error
        raise RuntimeError("Unexpected state: retries exhausted but no error")

    async def _parse_openai_stream_response(
        self,
        start_datetime: datetime,
        response: Any,
        structured_model: Type[BaseModel] | None = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        sanitized_response = _SanitizedStream(response)
        async for parsed in super()._parse_openai_stream_response(
            start_datetime=start_datetime,
            response=sanitized_response,
            structured_model=structured_model,
        ):
            if sanitized_response.extra_contents:
                for block in parsed.content:
                    if block.get("type") != "tool_use":
                        continue
                    tool_id = block.get("id")
                    if not isinstance(tool_id, str):
                        continue
                    ec = sanitized_response.extra_contents.get(tool_id)
                    if ec:
                        block["extra_content"] = ec
            yield parsed
