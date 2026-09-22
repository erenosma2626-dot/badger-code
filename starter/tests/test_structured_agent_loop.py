"""End-to-end loop test for StructuredToolAgent, using a scripted fake LLM
client and a fake container environment — no real network/Docker. Verifies
the tool-calling loop reaches task_complete via a terminal_exec call, and
that a turn with no tool call gets nudged rather than silently dropped
(mirrors tests/test_agent_stuck_loop.py's style for BaselineAgent).
"""

import asyncio
import pathlib
from dataclasses import dataclass

import pytest

from agent.agent import StructuredToolAgent


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    return_code: int


class FakeEnvironment:
    async def exec(self, command: str, timeout_sec: int) -> FakeExecResult:
        return FakeExecResult("__AGENT_CWD_AFTER__:/app\n", "", 0)


class FakeContext:
    def __init__(self):
        self.n_input_tokens = 0
        self.n_output_tokens = 0
        self.metadata = {}


class FakeLLM:
    """Scripted responses: first call is a nudge-worthy empty response,
    second calls terminal_exec, third calls task_complete."""

    def __init__(self, model_name=None):
        self.calls = 0

    async def chat_tools(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return "thinking...", [], {"prompt_tokens": 5, "completion_tokens": 2}
        if self.calls == 2:
            return (
                "",
                [{"id": "c1", "name": "terminal_exec", "arguments": {"command": "ls"}}],
                {"prompt_tokens": 5, "completion_tokens": 2},
            )
        return (
            "",
            [{"id": "c2", "name": "task_complete", "arguments": {"evidence": "ls ran clean"}}],
            {"prompt_tokens": 5, "completion_tokens": 2},
        )


def test_structured_agent_reaches_task_complete_and_records_evidence(monkeypatch):
    import agent.agent as agent_module

    monkeypatch.setattr(agent_module, "LLMClient", FakeLLM)

    sut = StructuredToolAgent(logs_dir=pathlib.Path("/tmp"), model_name="fake-model")
    ctx = FakeContext()
    asyncio.run(sut.run("do the thing", FakeEnvironment(), ctx))

    assert ctx.metadata["finished"] is True
    assert ctx.metadata["termination_reason"] == "task_complete"
    # The nudge for the empty first turn must have been injected.
    nudge_seen = any(
        m.get("role") == "user" and "didn't call any of the four tools" in m.get("content", "")
        for m in ctx.metadata["messages"]
    )
    assert nudge_seen
    # The terminal_exec call's receipt must have been fed back as a tool message.
    tool_msgs = [m for m in ctx.metadata["messages"] if m.get("role") == "tool"]
    assert any("exit_code" in m["content"] for m in tool_msgs)


class FakeLLMAlwaysEmpty:
    """Never calls a tool; used to check that the rejected raw content is
    logged (docs/v0.4-diagnosis-toolcall.md), not silently dropped."""

    def __init__(self, model_name=None):
        self.calls = 0

    async def chat_tools(self, messages, tools):
        self.calls += 1
        return (
            'I will call write_file with path=/app/main.c now.',
            [],
            {"prompt_tokens": 5, "completion_tokens": 2, "finish_reason": "length"},
        )


def test_structured_agent_logs_raw_content_when_no_tool_call_is_recognized(
    monkeypatch, caplog
):
    import logging
    import pathlib

    import agent.agent as agent_module

    monkeypatch.setattr(agent_module, "LLMClient", FakeLLMAlwaysEmpty)
    monkeypatch.setattr(agent_module, "MAX_TURNS", 2)

    sut = StructuredToolAgent(logs_dir=pathlib.Path("/tmp"), model_name="fake-model")
    sut.logger = logging.getLogger("test-structured-agent")
    ctx = FakeContext()

    with caplog.at_level(logging.WARNING, logger="test-structured-agent"):
        asyncio.run(sut.run("do the thing", FakeEnvironment(), ctx))

    assert any(
        "write_file with path=/app/main.c" in record.getMessage()
        and "finish_reason=length" in record.getMessage()
        for record in caplog.records
    )


def test_structured_agent_dispatches_write_file_with_append_true(monkeypatch):
    import agent.agent as agent_module

    captured_kwargs = {}

    async def fake_structured_write_file(environment, path, content, timeout_sec, append=False):
        captured_kwargs["path"] = path
        captured_kwargs["content"] = content
        captured_kwargs["append"] = append
        from agent.structured_tools import ExecutionReceipt
        return ExecutionReceipt(
            tool="write_file",
            exit_code=0,
            content_sha256="fakehash",
            content_bytes=len(content),
            changed_paths=[path],
        )

    monkeypatch.setattr(agent_module, "structured_write_file", fake_structured_write_file)

    class ScriptedLLM:
        def __init__(self, model_name=None):
            self.calls = 0

        async def chat_tools(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return (
                    "",
                    [{"id": "c1", "name": "write_file", "arguments": {"path": "/app/test.txt", "content": "more data", "append": True}}],
                    {"prompt_tokens": 5, "completion_tokens": 2},
                )
            return (
                "",
                [{"id": "c2", "name": "task_complete", "arguments": {"evidence": "appended"}}],
                {"prompt_tokens": 5, "completion_tokens": 2},
            )

    monkeypatch.setattr(agent_module, "LLMClient", ScriptedLLM)

    sut = StructuredToolAgent(logs_dir=pathlib.Path("/tmp"), model_name="fake-model")
    ctx = FakeContext()
    asyncio.run(sut.run("do the thing", FakeEnvironment(), ctx))

    assert captured_kwargs.get("append") is True

