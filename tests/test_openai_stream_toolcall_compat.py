# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from copaw.providers.openai_chat_model_compat import (
    COPAW_MODEL_BACKOFF_BASE,
    COPAW_MODEL_BACKOFF_CAP,
    COPAW_MODEL_RETRIES,
    OpenAIChatModelCompat,
    _compute_backoff_seconds,
    _get_backoff_base,
    _get_backoff_cap,
    _get_model_retries,
    _is_retryable_error,
    _sanitize_tool_call,
)


class CompatHarnessOpenAIChatModel(OpenAIChatModelCompat):
    async def parse_stream_for_test(
        self,
        start_datetime: datetime,
        stream: Any,
    ) -> list[Any]:
        responses = []
        async for response in self._parse_openai_stream_response(
            start_datetime,
            stream,
        ):
            responses.append(response)
        return responses


class FakeAsyncStream:
    def __init__(self, items: list[Any]):
        self._items = items
        self._iter = None

    async def __aenter__(self) -> "FakeAsyncStream":
        self._iter = iter(self._items)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def __aiter__(self) -> "FakeAsyncStream":
        return self

    async def __anext__(self) -> Any:
        assert self._iter is not None
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _make_chunk(tool_calls: list[Any]) -> Any:
    delta = SimpleNamespace(
        reasoning_content=None,
        content=None,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(usage=None, choices=[choice])


async def test_stream_parser_skips_tool_call_without_function() -> None:
    model = CompatHarnessOpenAIChatModel(
        "dummy",
        api_key="sk-test",
        stream=True,
    )

    malformed_tool_call = SimpleNamespace(
        index=0,
        id="call_bad",
        function=None,
    )
    none_arguments_tool_call = SimpleNamespace(
        index=1,
        id="call_partial",
        function=SimpleNamespace(name="ping", arguments=None),
    )
    valid_tool_call = SimpleNamespace(
        index=0,
        id="call_ok",
        function=SimpleNamespace(name="ping", arguments='{"x":1}'),
    )

    stream = FakeAsyncStream(
        [
            _make_chunk([malformed_tool_call]),
            _make_chunk([none_arguments_tool_call]),
            _make_chunk([valid_tool_call]),
        ],
    )

    responses = await model.parse_stream_for_test(
        datetime.now(),
        stream,
    )

    assert responses
    tool_blocks = [
        block
        for response in responses
        for block in response.content
        if block.get("type") == "tool_use"
    ]
    assert tool_blocks
    assert tool_blocks[-1]["name"] == "ping"
    assert tool_blocks[-1]["input"] == {"x": 1}


def test_sanitize_tool_call_normalizes_non_string_arguments() -> None:
    none_arguments_tool_call = SimpleNamespace(
        index=0,
        id="call_partial",
        function=SimpleNamespace(name="ping", arguments=None),
    )
    non_string_arguments_tool_call = SimpleNamespace(
        index=1,
        id="call_dict",
        function=SimpleNamespace(name="ping", arguments={"x": 2}),
    )
    missing_arguments_tool_call = SimpleNamespace(
        index=2,
        id="call_missing_args",
        function=SimpleNamespace(name="ping"),
    )
    missing_name_tool_call = SimpleNamespace(
        index=3,
        id="call_missing_name",
        function=SimpleNamespace(arguments={"x": 3}),
    )
    missing_name_and_arguments_tool_call = SimpleNamespace(
        index=4,
        id="call_missing_both",
        function=SimpleNamespace(),
    )

    sanitized_none_arguments = _sanitize_tool_call(none_arguments_tool_call)
    assert sanitized_none_arguments is not None
    assert sanitized_none_arguments.function.name == "ping"
    assert sanitized_none_arguments.function.arguments == ""

    sanitized_non_string_arguments = _sanitize_tool_call(
        non_string_arguments_tool_call,
    )
    assert sanitized_non_string_arguments is not None
    assert sanitized_non_string_arguments.function.name == "ping"
    assert isinstance(sanitized_non_string_arguments.function.arguments, str)
    assert json.loads(sanitized_non_string_arguments.function.arguments) == {
        "x": 2,
    }

    sanitized_missing_arguments = _sanitize_tool_call(
        missing_arguments_tool_call,
    )
    assert sanitized_missing_arguments is not None
    assert sanitized_missing_arguments.function.name == "ping"
    assert sanitized_missing_arguments.function.arguments == ""

    sanitized_missing_name = _sanitize_tool_call(missing_name_tool_call)
    assert sanitized_missing_name is not None
    assert sanitized_missing_name.function.name == ""
    assert isinstance(sanitized_missing_name.function.arguments, str)
    assert json.loads(sanitized_missing_name.function.arguments) == {"x": 3}

    sanitized_missing_name_and_arguments = _sanitize_tool_call(
        missing_name_and_arguments_tool_call,
    )
    assert sanitized_missing_name_and_arguments is not None
    assert sanitized_missing_name_and_arguments.function.name == ""
    assert sanitized_missing_name_and_arguments.function.arguments == ""


def test_get_model_retries_default() -> None:
    """Test _get_model_retries returns default value."""
    with patch.dict("os.environ", {}, clear=True):
        assert _get_model_retries() == COPAW_MODEL_RETRIES


def test_get_model_retries_from_env() -> None:
    """Test _get_model_retries reads from environment variable."""
    with patch.dict("os.environ", {"COPAW_MODEL_RETRIES": "5"}):
        assert _get_model_retries() == 5


def test_get_model_retries_invalid_env() -> None:
    """Test _get_model_retries falls back to default on invalid value."""
    with patch.dict("os.environ", {"COPAW_MODEL_RETRIES": "invalid"}):
        assert _get_model_retries() == COPAW_MODEL_RETRIES


def test_get_backoff_base_default() -> None:
    """Test _get_backoff_base returns default value."""
    with patch.dict("os.environ", {}, clear=True):
        assert _get_backoff_base() == COPAW_MODEL_BACKOFF_BASE


def test_get_backoff_base_from_env() -> None:
    """Test _get_backoff_base reads from environment variable."""
    with patch.dict("os.environ", {"COPAW_MODEL_BACKOFF_BASE": "2.5"}):
        assert _get_backoff_base() == 2.5


def test_get_backoff_base_invalid_env() -> None:
    """Test _get_backoff_base falls back to default on invalid value."""
    with patch.dict("os.environ", {"COPAW_MODEL_BACKOFF_BASE": "invalid"}):
        assert _get_backoff_base() == COPAW_MODEL_BACKOFF_BASE


def test_get_backoff_cap_default() -> None:
    """Test _get_backoff_cap returns default value."""
    with patch.dict("os.environ", {}, clear=True):
        assert _get_backoff_cap() == COPAW_MODEL_BACKOFF_CAP


def test_get_backoff_cap_from_env() -> None:
    """Test _get_backoff_cap reads from environment variable."""
    with patch.dict("os.environ", {"COPAW_MODEL_BACKOFF_CAP": "30.0"}):
        assert _get_backoff_cap() == 30.0


def test_get_backoff_cap_invalid_env() -> None:
    """Test _get_backoff_cap falls back to default on invalid value."""
    with patch.dict("os.environ", {"COPAW_MODEL_BACKOFF_CAP": "invalid"}):
        assert _get_backoff_cap() == COPAW_MODEL_BACKOFF_CAP


def test_compute_backoff_seconds_exponential() -> None:
    """Test exponential backoff calculation."""
    base = 1.0
    cap = 60.0

    # Test exponential growth
    assert _compute_backoff_seconds(0, base, cap) == 1.0  # 1 * 2^0
    assert _compute_backoff_seconds(1, base, cap) == 2.0  # 1 * 2^1
    assert _compute_backoff_seconds(2, base, cap) == 4.0  # 1 * 2^2
    assert _compute_backoff_seconds(3, base, cap) == 8.0  # 1 * 2^3


def test_compute_backoff_seconds_with_cap() -> None:
    """Test backoff is capped at maximum value."""
    base = 1.0
    cap = 60.0

    # Test cap is applied for large attempts
    assert _compute_backoff_seconds(10, base, cap) == 60.0  # capped at 60


def _make_mock_response(status_code: int) -> Any:
    """Create a mock httpx.Response for OpenAI error testing."""
    return SimpleNamespace(
        status_code=status_code,
        request=SimpleNamespace(),
        headers=SimpleNamespace(get=lambda key: None),
    )


def test_is_retryable_error_with_rate_limit_error() -> None:
    """Test RateLimitError is retryable."""
    from openai import RateLimitError

    error = RateLimitError(
        message="Rate limit exceeded",
        response=_make_mock_response(429),
        body=None,
    )
    assert _is_retryable_error(error) is True


def test_is_retryable_error_with_internal_server_error() -> None:
    """Test InternalServerError is retryable."""
    from openai import InternalServerError

    error = InternalServerError(
        message="Internal server error",
        response=_make_mock_response(500),
        body=None,
    )
    assert _is_retryable_error(error) is True


def test_is_retryable_error_with_api_error_status_code() -> None:
    """Test APIError with retryable status codes.

    Note: APIError is the base class and takes a 'request' parameter,
    not 'response'. The status_code comes from the request.
    """
    from openai import APIError

    mock_request = SimpleNamespace(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
    )

    # Create APIError with retryable status code by setting status_code
    # attribute
    error_503 = APIError(
        message="Service unavailable",
        request=mock_request,
        body=None,
    )
    # Manually set status_code for testing
    error_503.status_code = 503
    assert _is_retryable_error(error_503) is True

    # Test 502 Bad Gateway
    error_502 = APIError(
        message="Bad gateway",
        request=mock_request,
        body=None,
    )
    error_502.status_code = 502
    assert _is_retryable_error(error_502) is True


def test_is_retryable_error_with_non_retryable_status_code() -> None:
    """Test APIError with non-retryable status codes."""
    from openai import APIError

    mock_request = SimpleNamespace(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
    )

    # Test 400 Bad Request (not retryable)
    error_400 = APIError(
        message="Bad request",
        request=mock_request,
        body=None,
    )
    error_400.status_code = 400
    assert _is_retryable_error(error_400) is False

    # Test 401 Unauthorized (not retryable)
    error_401 = APIError(
        message="Unauthorized",
        request=mock_request,
        body=None,
    )
    error_401.status_code = 401
    assert _is_retryable_error(error_401) is False


@pytest.mark.asyncio
async def test_call_retry_on_transient_error() -> None:
    """Test that __call__ retries on transient errors."""
    from openai import InternalServerError

    model = OpenAIChatModelCompat(
        "dummy",
        api_key="sk-test",
        stream=False,
    )

    # Mock the parent __call__ to fail twice then succeed
    call_count = 0

    async def mock_parent_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise InternalServerError(
                message="Service unavailable",
                response=_make_mock_response(503),
                body=None,
            )
        return {"content": "Success"}

    with (
        patch.object(
            OpenAIChatModelCompat.__bases__[0],
            "__call__",
            mock_parent_call,
        ),
        patch("asyncio.sleep", AsyncMock()),
    ):  # Skip actual sleep
        result = await model.__call__()

    assert call_count == 3
    assert result == {"content": "Success"}


@pytest.mark.asyncio
async def test_call_raises_after_max_retries() -> None:
    """Test that __call__ raises the last error after max retries."""
    from openai import InternalServerError

    model = OpenAIChatModelCompat(
        "dummy",
        api_key="sk-test",
        stream=False,
    )

    # Mock the parent __call__ to always fail
    call_count = 0

    async def mock_parent_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise InternalServerError(
            message="Service unavailable",
            response=_make_mock_response(503),
            body=None,
        )

    with (
        patch.object(
            OpenAIChatModelCompat.__bases__[0],
            "__call__",
            mock_parent_call,
        ),
        patch("asyncio.sleep", AsyncMock()),
    ):  # Skip actual sleep
        with pytest.raises(InternalServerError):
            await model.__call__()

    # Should have tried initial call + 3 retries = 4 total
    assert call_count == 4


@pytest.mark.asyncio
async def test_call_no_retry_on_non_retryable_error() -> None:
    """Test that __call__ does not retry on non-retryable errors."""
    from openai import AuthenticationError

    model = OpenAIChatModelCompat(
        "dummy",
        api_key="sk-test",
        stream=False,
    )

    call_count = 0

    async def mock_parent_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise AuthenticationError(
            message="Invalid API key",
            response=_make_mock_response(401),
            body=None,
        )

    with patch.object(
        OpenAIChatModelCompat.__bases__[0],
        "__call__",
        mock_parent_call,
    ):
        with pytest.raises(AuthenticationError):
            await model.__call__()

    # Should have tried only once (no retry)
    assert call_count == 1


@pytest.mark.asyncio
async def test_call_success_no_retry() -> None:
    """Test that __call__ succeeds without retry on first attempt."""
    model = OpenAIChatModelCompat(
        "dummy",
        api_key="sk-test",
        stream=False,
    )

    call_count = 0

    async def mock_parent_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {"content": "Hello"}

    with patch.object(
        OpenAIChatModelCompat.__bases__[0],
        "__call__",
        mock_parent_call,
    ):
        result = await model.__call__()

    assert call_count == 1
    assert result == {"content": "Hello"}
