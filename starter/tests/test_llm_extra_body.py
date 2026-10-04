"""v0.7.1 — LLM_EXTRA_BODY: provider-specific request fields from env,
e.g. {"chat_template_kwargs": {"enable_thinking": true}} to turn on Qwen's
thinking mode (Nebius served Qwen3.8-27B with thinking off: 40–260 output
tokens/turn in q38-canary-v07), or an OpenRouter `provider` constraint."""

import asyncio
from types import SimpleNamespace

import pytest

from agent.llm import LLMClient


class Rec:
    async def create(self, **kwargs):
        self.kwargs = kwargs
        msg = SimpleNamespace(content="ok", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)


def _client(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("LLM_EXTRA_BODY", raising=False)
    else:
        monkeypatch.setenv("LLM_EXTRA_BODY", value)
    monkeypatch.setenv("LLM_MODEL", "m")
    c = LLMClient()
    rec = Rec()
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=rec))
    return c, rec


def test_extra_body_is_sent_on_both_paths(monkeypatch):
    c, rec = _client(monkeypatch, '{"chat_template_kwargs": {"enable_thinking": true}}')
    asyncio.run(c.chat_tools([], tools=[]))
    assert rec.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}
    asyncio.run(c.chat([]))
    assert rec.kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


def test_no_extra_body_when_unset(monkeypatch):
    c, rec = _client(monkeypatch, None)
    asyncio.run(c.chat_tools([], tools=[]))
    assert "extra_body" not in rec.kwargs


def test_invalid_json_fails_loudly(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_BODY", "{not json")
    monkeypatch.setenv("LLM_MODEL", "m")
    with pytest.raises(ValueError, match="LLM_EXTRA_BODY"):
        LLMClient()
