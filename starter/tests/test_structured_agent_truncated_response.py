"""v0.4.1 madde 2: when the model's response has no tool_calls because it
was cut off by max_tokens (finish_reason="length"), StructuredToolAgent
must nudge with TRUNCATED_RESPONSE_MESSAGE (telling it to stop repeating
the same truncated content) instead of the generic STRUCTURED_NUDGE_MESSAGE
(which just says "you didn't call a tool" and doesn't address the actual
cause, observed to cause 18+ turn loops in chess-best-move/2RrorEW and
regex-log/FZorHju).
"""

import asyncio
import pathlib
from dataclasses import dataclass

from agent.agent import StructuredToolAgent
from agent.prompts import STRUCTURED_NUDGE_MESSAGE, TRUNCATED_RESPONSE_MESSAGE


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


def make_scripted_llm(turns: list[tuple[str, list[dict], dict]]):
    class _LLM:
        def __init__(self, model_name=None):
            self.calls = 0

        async def chat_tools(self, messages, tools):
            idx = min(self.calls, len(turns) - 1)
            self.calls += 1
            text, tool_calls, usage = turns[idx]
            return text, tool_calls, usage

    return _LLM


def run_structured_agent(monkeypatch, env, turns, max_turns=5):
    import agent.agent as agent_module

    monkeypatch.setattr(agent_module, "LLMClient", make_scripted_llm(turns))
    monkeypatch.setattr(agent_module, "MAX_TURNS", max_turns)

    sut = StructuredToolAgent(logs_dir=pathlib.Path("/tmp"), model_name="fake-model")
    ctx = FakeContext()
    asyncio.run(sut.run("do the thing", env, ctx))
    return ctx


def test_finish_reason_length_gets_truncated_response_message(monkeypatch):
    env = FakeEnvironment()
    turns = [
        ("partial content that never clos", [], {"prompt_tokens": 1, "completion_tokens": 1, "finish_reason": "length"}),
        ("", [{"id": "c1", "name": "task_complete", "arguments": {"evidence": "done"}}], {"prompt_tokens": 1, "completion_tokens": 1}),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)

    nudge_messages = [
        m["content"] for m in ctx.metadata["messages"] if m.get("role") == "user"
    ]
    assert any(TRUNCATED_RESPONSE_MESSAGE in c for c in nudge_messages)
    assert not any(
        c == STRUCTURED_NUDGE_MESSAGE for c in nudge_messages
    )


def test_finish_reason_other_still_gets_generic_nudge(monkeypatch):
    env = FakeEnvironment()
    turns = [
        ("narrating instead of calling a tool", [], {"prompt_tokens": 1, "completion_tokens": 1, "finish_reason": "stop"}),
        ("", [{"id": "c1", "name": "task_complete", "arguments": {"evidence": "done"}}], {"prompt_tokens": 1, "completion_tokens": 1}),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)

    nudge_messages = [
        m["content"] for m in ctx.metadata["messages"] if m.get("role") == "user"
    ]
    assert any(c == STRUCTURED_NUDGE_MESSAGE for c in nudge_messages)
    assert not any(TRUNCATED_RESPONSE_MESSAGE in c for c in nudge_messages)


def test_repeated_length_truncation_on_same_write_file_target_gets_append_advice(monkeypatch):
    env = FakeEnvironment()
    partial_write = '{"name": "write_file", "arguments": {"path": "/app/huge.py", "content": "def massive():'
    turns = [
        (partial_write, [], {"prompt_tokens": 1, "completion_tokens": 1, "finish_reason": "length"}),
        (partial_write, [], {"prompt_tokens": 1, "completion_tokens": 1, "finish_reason": "length"}),
        ("", [{"id": "c1", "name": "task_complete", "arguments": {"evidence": "done"}}], {"prompt_tokens": 1, "completion_tokens": 1}),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns, max_turns=5)

    user_messages = [
        m["content"] for m in ctx.metadata["messages"] if m.get("role") == "user"
    ]
    nudges = user_messages[1:]
    # First truncation gets standard TRUNCATED_RESPONSE_MESSAGE
    assert TRUNCATED_RESPONSE_MESSAGE in nudges[0]
    assert "append=true" not in nudges[0]

    # Second consecutive truncation on same target gets enhanced advice
    assert len(nudges) >= 2
    assert TRUNCATED_RESPONSE_MESSAGE in nudges[1]
    assert "append=true" in nudges[1]
    assert "/app/huge.py" in nudges[1]

