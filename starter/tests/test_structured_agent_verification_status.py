"""Tests for verification_status tracking in StructuredToolAgent (v0.4
spec §1.1 madde 1): derived from the execution-receipt stream rather than
BaselineAgent's shell-command classifier, since StructuredToolAgent has a
dedicated write_file tool (the only "edit") and terminal_exec is the only
generic "did something get verified" signal.

Status semantics (mirrors BaselineAgent's compute_verification_status):
- "not_applicable": no write_file call has happened yet.
- "missing": a write_file happened and no terminal_exec with exit_code=0
  has run since.
- "passed": the most recent write_file is covered by a terminal_exec with
  exit_code=0 that ran after it.
- "stale": some terminal_exec succeeded at some point, but a later
  write_file has happened without a fresh successful terminal_exec since.
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
    """Bootstrap call always succeeds; scripted terminal_exec results are
    consumed in order after that for any command containing MARKER_OK or
    MARKER_FAIL, otherwise defaults to exit 0."""

    def __init__(self, exec_results: list[FakeExecResult] | None = None):
        self._results = exec_results or []
        self._idx = 0
        self.calls: list[str] = []

    async def exec(self, command: str, timeout_sec: int) -> FakeExecResult:
        self.calls.append(command)
        if "__AGENT_CWD_AFTER__" not in command:
            return FakeExecResult("__AGENT_CWD_AFTER__:/app\n", "", 0)
        if self._idx < len(self._results):
            result = self._results[self._idx]
            self._idx += 1
            return result
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


def run_structured_agent(monkeypatch, env, turns, max_turns=10):
    import agent.agent as agent_module

    monkeypatch.setattr(agent_module, "LLMClient", make_scripted_llm(turns))
    monkeypatch.setattr(agent_module, "MAX_TURNS", max_turns)

    sut = StructuredToolAgent(logs_dir=pathlib.Path("/tmp"), model_name="fake-model")
    ctx = FakeContext()
    asyncio.run(sut.run("do the thing", env, ctx))
    return ctx


def test_verification_status_is_not_applicable_before_any_write_file(monkeypatch):
    env = FakeEnvironment()
    turns = [
        ("", [{"id": "c1", "name": "terminal_exec", "arguments": {"command": "ls"}}]),
        ("", [{"id": "c2", "name": "task_complete", "arguments": {"evidence": "looked around"}}]),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)
    assert ctx.metadata["verification_status"] == "not_applicable"


def test_verification_status_is_missing_after_write_file_with_no_terminal_exec(monkeypatch):
    env = FakeEnvironment()
    turns = [
        ("", [{"id": "c1", "name": "write_file", "arguments": {"path": "/app/x.py", "content": "print(1)"}}]),
        ("", [{"id": "c2", "name": "task_complete", "arguments": {"evidence": "wrote the file"}}]),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)
    assert ctx.metadata["verification_status"] == "missing"


def test_verification_status_is_passed_after_successful_terminal_exec_following_write(monkeypatch):
    env = FakeEnvironment(exec_results=[FakeExecResult("ok\n", "", 0)])
    turns = [
        ("", [{"id": "c1", "name": "write_file", "arguments": {"path": "/app/x.py", "content": "print(1)"}}]),
        ("", [{"id": "c2", "name": "terminal_exec", "arguments": {"command": "python3 /app/x.py"}}]),
        ("", [{"id": "c3", "name": "task_complete", "arguments": {"evidence": "ran it, exit 0"}}]),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)
    assert ctx.metadata["verification_status"] == "passed"


def test_verification_status_is_stale_after_a_new_edit_following_success(monkeypatch):
    env = FakeEnvironment(exec_results=[FakeExecResult("ok\n", "", 0)])
    turns = [
        ("", [{"id": "c1", "name": "write_file", "arguments": {"path": "/app/x.py", "content": "print(1)"}}]),
        ("", [{"id": "c2", "name": "terminal_exec", "arguments": {"command": "python3 /app/x.py"}}]),
        ("", [{"id": "c3", "name": "write_file", "arguments": {"path": "/app/x.py", "content": "print(2)"}}]),
        ("", [{"id": "c4", "name": "task_complete", "arguments": {"evidence": "edited again"}}]),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)
    assert ctx.metadata["verification_status"] == "stale"


def test_verification_status_stays_missing_after_a_failed_terminal_exec(monkeypatch):
    env = FakeEnvironment(exec_results=[FakeExecResult("boom\n", "", 1)])
    turns = [
        ("", [{"id": "c1", "name": "write_file", "arguments": {"path": "/app/x.py", "content": "print(1)"}}]),
        ("", [{"id": "c2", "name": "terminal_exec", "arguments": {"command": "python3 /app/x.py"}}]),
        ("", [{"id": "c3", "name": "task_complete", "arguments": {"evidence": "ran it"}}]),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)
    assert ctx.metadata["verification_status"] == "missing"
