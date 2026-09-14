"""Tests for LLMClient.chat_tools() — the native function-calling path
that powers StructuredToolAgent. Monkeypatches the underlying OpenAI
client's chat.completions.create() so no real endpoint is contacted,
same spirit as the FakeEnvironment used for tools.py tests.
"""

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from agent.llm import LLMClient


@dataclass
class FakeToolCallFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeToolCallFunction


@dataclass
class FakeMessage:
    content: str | None = None
    tool_calls: list = field(default_factory=list)


class FakeCompletions:
    def __init__(self, message: FakeMessage, usage=None):
        self._message = message
        self._usage = usage

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        choice = SimpleNamespace(message=self._message)
        return SimpleNamespace(choices=[choice], usage=self._usage)


def _client_with(message: FakeMessage, usage=None) -> LLMClient:
    client = LLMClient.__new__(LLMClient)
    client.model = "test-model"
    client.temperature = 0.2
    client.max_tokens = 2048
    completions = FakeCompletions(message, usage)
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    client._completions = completions
    return client


def test_chat_tools_decodes_json_arguments_into_a_dict():
    message = FakeMessage(
        content="",
        tool_calls=[
            FakeToolCall(
                id="call_1",
                function=FakeToolCallFunction(
                    name="terminal_exec", arguments='{"command": "ls -la"}'
                ),
            )
        ],
    )
    client = _client_with(message)
    text, tool_calls, usage = asyncio.run(client.chat_tools([], tools=[]))

    assert text == ""
    assert tool_calls == [
        {"id": "call_1", "name": "terminal_exec", "arguments": {"command": "ls -la"}}
    ]


def test_chat_tools_returns_empty_list_when_model_does_not_call_a_tool():
    message = FakeMessage(content="I need more info first.", tool_calls=[])
    client = _client_with(message)
    text, tool_calls, usage = asyncio.run(client.chat_tools([], tools=[]))

    assert text == "I need more info first."
    assert tool_calls == []


def test_chat_tools_survives_malformed_json_arguments():
    message = FakeMessage(
        content="",
        tool_calls=[
            FakeToolCall(
                id="call_1",
                function=FakeToolCallFunction(name="task_complete", arguments="not json"),
            )
        ],
    )
    client = _client_with(message)
    text, tool_calls, usage = asyncio.run(client.chat_tools([], tools=[]))

    assert tool_calls == [{"id": "call_1", "name": "task_complete", "arguments": {}}]


def test_chat_tools_surfaces_finish_reason_for_diagnosing_rejected_tool_calls():
    """docs/v0.4-diagnosis-toolcall.md: a completion cut off by max_tokens
    (finish_reason="length") is a strong, checkable explanation for a
    malformed/empty tool call — the caller needs this signal, not just the
    fact that tool_calls came back empty."""
    message = FakeMessage(content="partial tool call json that never clos", tool_calls=[])
    client = _client_with(message)
    completions = client._completions
    original_create = completions.create

    async def create_with_finish_reason(**kwargs):
        response = await original_create(**kwargs)
        response.choices[0].finish_reason = "length"
        return response

    completions.create = create_with_finish_reason

    text, tool_calls, usage = asyncio.run(client.chat_tools([], tools=[]))

    assert tool_calls == []
    assert usage["finish_reason"] == "length"


def test_chat_tools_passes_tools_and_tool_choice_auto_to_the_api():
    message = FakeMessage(content="", tool_calls=[])
    client = _client_with(message)
    tools_schema = [{"type": "function", "function": {"name": "terminal_exec"}}]
    asyncio.run(client.chat_tools([{"role": "user", "content": "hi"}], tools=tools_schema))

    kwargs = client._completions.last_kwargs
    assert kwargs["tools"] == tools_schema
    assert kwargs["tool_choice"] == "auto"
