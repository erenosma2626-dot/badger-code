"""v0.6 madde 3: bounded retry + exponential backoff in LLMClient for
transient failures (connection errors, timeouts, 5xx, httpx
RemoteProtocolError). 4xx/invalid requests are NOT retried."""

import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

import agent.llm as llm_module
from agent.llm import LLMClient

_REQ = httpx.Request("POST", "http://x/v1/chat/completions")


def _status_err(cls, code):
    return cls("boom", response=httpx.Response(code, request=_REQ), body=None)


def _ok_response():
    msg = SimpleNamespace(content="hi", tool_calls=[])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)


class FlakyCompletions:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return _ok_response()


def _client(errors, monkeypatch):
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(llm_module.asyncio, "sleep", fake_sleep)
    c = LLMClient.__new__(LLMClient)
    c.model, c.temperature, c.max_tokens = "m", 0.2, 100
    comp = FlakyCompletions(errors)
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    return c, comp, sleeps


@pytest.mark.parametrize("err", [
    openai.APIConnectionError(request=_REQ),
    openai.APITimeoutError(request=_REQ),
    _status_err(openai.InternalServerError, 503),
    httpx.RemoteProtocolError("peer closed"),
])
def test_transient_errors_are_retried(monkeypatch, err):
    c, comp, sleeps = _client([err, err], monkeypatch)
    text, _, _ = asyncio.run(c.chat_tools([], []))
    assert text == "hi"
    assert comp.calls == 3
    assert sleeps and sleeps[1] > sleeps[0]


def test_gives_up_after_max_attempts(monkeypatch):
    err = openai.APIConnectionError(request=_REQ)
    c, comp, sleeps = _client([err] * 10, monkeypatch)
    with pytest.raises(openai.APIConnectionError):
        asyncio.run(c.chat([]))
    assert comp.calls == 3
    assert sum(sleeps) <= 60


def test_4xx_is_not_retried(monkeypatch):
    err = _status_err(openai.BadRequestError, 400)
    c, comp, sleeps = _client([err], monkeypatch)
    with pytest.raises(openai.BadRequestError):
        asyncio.run(c.chat_tools([], []))
    assert comp.calls == 1
    assert sleeps == []
