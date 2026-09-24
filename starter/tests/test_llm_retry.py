"""Tests for LLMClient transient error retry with exponential backoff (v0.6 prep item 3).

Transient errors (APIConnectionError, APITimeoutError, 5xx, httpcore RemoteProtocolError)
must be retried up to 3 times with exponential backoff and jitter.
4xx client errors (400, 401, 404, 422) must NOT be retried.
Total backoff wait must not exceed ~30s.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpcore
import httpx
import openai
import pytest

from agent.llm import LLMClient, is_transient_error


def _dummy_request() -> httpx.Request:
    return httpx.Request("POST", "http://test")


def _status_error(status_code: int) -> openai.APIStatusError:
    req = _dummy_request()
    resp = httpx.Response(status_code, request=req)
    if status_code == 400:
        return openai.BadRequestError("bad request", response=resp, body=None)
    if status_code == 401:
        return openai.AuthenticationError("unauthorized", response=resp, body=None)
    if status_code == 404:
        return openai.NotFoundError("not found", response=resp, body=None)
    if status_code == 422:
        return openai.UnprocessableEntityError("unprocessable", response=resp, body=None)
    if status_code == 500:
        return openai.InternalServerError("internal server error", response=resp, body=None)
    return openai.APIStatusError(f"status {status_code}", response=resp, body=None)


def test_is_transient_error_identifies_retryable_exceptions():
    req = _dummy_request()
    assert is_transient_error(openai.APIConnectionError(request=req)) is True
    assert is_transient_error(openai.APITimeoutError(request=req)) is True
    assert is_transient_error(httpcore.RemoteProtocolError("protocol error")) is True
    assert is_transient_error(_status_error(500)) is True
    assert is_transient_error(_status_error(502)) is True
    assert is_transient_error(_status_error(503)) is True
    assert is_transient_error(_status_error(504)) is True


def test_is_transient_error_rejects_non_transient_errors():
    assert is_transient_error(_status_error(400)) is False
    assert is_transient_error(_status_error(401)) is False
    assert is_transient_error(_status_error(404)) is False
    assert is_transient_error(_status_error(422)) is False
    assert is_transient_error(ValueError("invalid argument")) is False
    assert is_transient_error(KeyError("missing key")) is False


def _create_mock_client():
    client = LLMClient.__new__(LLMClient)
    client.model = "test-model"
    client.temperature = 0.2
    client.max_tokens = 2048
    client.max_retries = 3
    client.initial_backoff = 2.0
    client.backoff_factor = 2.0
    client.max_jitter = 0.5
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock()))
    )
    return client


@pytest.mark.asyncio
async def test_chat_retries_transient_error_and_eventually_succeeds(monkeypatch):
    client = _create_mock_client()
    req = _dummy_request()

    success_choice = SimpleNamespace(
        message=SimpleNamespace(content="Hello after retry", reasoning_content=None)
    )
    success_response = SimpleNamespace(choices=[success_choice], usage=None)

    # Fail twice with transient errors, succeed on 3rd attempt
    client._client.chat.completions.create.side_effect = [
        openai.APIConnectionError(request=req),
        httpcore.RemoteProtocolError("stream reset"),
        success_response,
    ]

    sleep_calls = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    text, usage = await client.chat([{"role": "user", "content": "hi"}])

    assert text == "Hello after retry"
    assert client._client.chat.completions.create.call_count == 3
    assert len(sleep_calls) == 2
    # Verify exponential backoff: ~2s for 1st retry, ~4s for 2nd retry (+ small jitter <= 0.5)
    assert 2.0 <= sleep_calls[0] <= 2.5
    assert 4.0 <= sleep_calls[1] <= 4.5


@pytest.mark.asyncio
async def test_chat_exhausts_retries_and_raises(monkeypatch):
    client = _create_mock_client()
    error_503 = _status_error(503)

    client._client.chat.completions.create.side_effect = error_503

    sleep_calls = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(openai.APIStatusError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])

    assert exc_info.value.status_code == 503
    # 1 initial call + 3 retries = 4 total calls
    assert client._client.chat.completions.create.call_count == 4
    assert len(sleep_calls) == 3
    assert 2.0 <= sleep_calls[0] <= 2.5
    assert 4.0 <= sleep_calls[1] <= 4.5
    assert 8.0 <= sleep_calls[2] <= 8.5
    # Total wait is well under ~30s
    assert sum(sleep_calls) < 30.0


@pytest.mark.asyncio
async def test_chat_does_not_retry_4xx_errors(monkeypatch):
    client = _create_mock_client()
    client._client.chat.completions.create.side_effect = _status_error(401)

    sleep_mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)

    with pytest.raises(openai.AuthenticationError):
        await client.chat([{"role": "user", "content": "hi"}])

    # No retries on 401 client error
    assert client._client.chat.completions.create.call_count == 1
    sleep_mock.assert_not_called()


@pytest.mark.asyncio
async def test_chat_tools_retries_transient_error(monkeypatch):
    client = _create_mock_client()
    req = _dummy_request()

    success_choice = SimpleNamespace(
        message=SimpleNamespace(
            content="",
            tool_calls=[
                SimpleNamespace(
                    id="call_abc",
                    function=SimpleNamespace(name="terminal_exec", arguments='{"command": "pwd"}'),
                )
            ],
        ),
        finish_reason="tool_calls",
    )
    success_response = SimpleNamespace(choices=[success_choice], usage=None)

    client._client.chat.completions.create.side_effect = [
        openai.APITimeoutError(request=req),
        success_response,
    ]

    sleep_calls = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    text, tool_calls, usage = await client.chat_tools(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "terminal_exec"}}],
    )

    assert tool_calls == [
        {"id": "call_abc", "name": "terminal_exec", "arguments": {"command": "pwd"}}
    ]
    assert client._client.chat.completions.create.call_count == 2
    assert len(sleep_calls) == 1
    assert 2.0 <= sleep_calls[0] <= 2.5
