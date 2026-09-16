"""Tests for the completion-evidence gate ported to StructuredToolAgent
(v0.4 spec §2.1, tightened): a task_complete call while verification is
pending/missing gets one nudge; a second task_complete is accepted only
if a genuine NEW tool call happened since the nudge, otherwise it is
rejected hard (terminal decision, no third nudge). Mirrors
tests/test_agent_completion_evidence_gate.py's style for BaselineAgent.
"""

import asyncio
import pathlib
from dataclasses import dataclass

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


def make_scripted_llm(turns: list[tuple[str, list[dict]]]):
    class _LLM:
        def __init__(self, model_name=None):
            self.calls = 0

        async def chat_tools(self, messages, tools):
            idx = min(self.calls, len(turns) - 1)
            self.calls += 1
            text, tool_calls = turns[idx]
            return text, tool_calls, {"prompt_tokens": 1, "completion_tokens": 1}

    return _LLM


def run_structured_agent(monkeypatch, turns, max_turns=20):
    import agent.agent as agent_module

    monkeypatch.setattr(agent_module, "LLMClient", make_scripted_llm(turns))
    monkeypatch.setattr(agent_module, "MAX_TURNS", max_turns)

    sut = StructuredToolAgent(logs_dir=pathlib.Path("/tmp"), model_name="fake-model")
    ctx = FakeContext()
    asyncio.run(sut.run("do the thing", FakeEnvironment(), ctx))
    return ctx


WRITE_CALL = {"id": "c1", "name": "write_file", "arguments": {"path": "/app/x.py", "content": "print(1)"}}
DONE_CALL = lambda i: {"id": f"d{i}", "name": "task_complete", "arguments": {"evidence": "trust me"}}


def test_first_task_complete_with_missing_evidence_is_nudged_not_accepted(monkeypatch):
    turns = [
        ("", [WRITE_CALL]),
        ("", [DONE_CALL(1)]),
        ("", [{"id": "c2", "name": "terminal_exec", "arguments": {"command": "python3 /app/x.py"}}]),
        ("", [DONE_CALL(2)]),
    ]
    ctx = run_structured_agent(monkeypatch, turns)
    assert ctx.metadata["turns"] >= 3
    assert ctx.metadata["termination_reason"] == "task_complete"


def test_second_task_complete_with_no_new_tool_call_is_rejected_hard(monkeypatch):
    turns = [
        ("", [WRITE_CALL]),
        ("", [DONE_CALL(1)]),
        ("", [DONE_CALL(2)]),
    ]
    ctx = run_structured_agent(monkeypatch, turns)
    assert ctx.metadata["termination_reason"] == "completion_rejected_no_new_evidence"
    assert ctx.metadata["finished"] is not True
    assert ctx.metadata["turns"] == 3


def test_second_task_complete_after_a_new_meaningful_tool_call_is_accepted(monkeypatch):
    turns = [
        ("", [WRITE_CALL]),
        ("", [DONE_CALL(1)]),
        ("", [{"id": "c2", "name": "terminal_exec", "arguments": {"command": "python3 /app/x.py"}}]),
        ("", [DONE_CALL(2)]),
    ]
    ctx = run_structured_agent(monkeypatch, turns)
    assert ctx.metadata["termination_reason"] == "task_complete"
    assert ctx.metadata["finished"] is True


def test_second_task_complete_after_only_a_read_file_readback_is_still_rejected(monkeypatch):
    """v0.4.1 madde 3 (tightened further): a read_file call after the nudge
    is often just the model re-reading its own edit back as "proof" — it
    is NOT meaningful new verification (see is_meaningful_verification),
    so this must still hard-reject, unlike the pre-v0.4.1 behavior where
    any tool call (including read_file) was accepted as sufficient."""
    turns = [
        ("", [WRITE_CALL]),
        ("", [DONE_CALL(1)]),
        ("", [{"id": "c2", "name": "read_file", "arguments": {"path": "/app/x.py"}}]),
        ("", [DONE_CALL(2)]),
    ]
    ctx = run_structured_agent(monkeypatch, turns)
    assert ctx.metadata["termination_reason"] == "completion_rejected_no_new_evidence"
    assert ctx.metadata["finished"] is not True
