"""v0.4.1 madde 3: verification-gate tightening + verification_status
passive-command distinction. Both bugs share the same root cause — any
terminal_exec with exit_code==0 after has_edited is treated as "verified",
even a passive/administrative command like `cat`, `ls`, or `chmod +x`
(sqlite/4wFNfuj: chmod +x counted as verification). A pure
is_meaningful_verification(command) blocklist function fixes both call
sites: (1) pending_verification clearing after has_edited, and (2) the
action_since_nudge completion-evidence gate (an agent that only re-reads
its own file with cat/read_file after a nudge must still be rejected —
regex-log b6wa6dk/xdXEGdG, log-summary 2okTmCh, chess-best-move mhL8tVf).
"""

import asyncio
import pathlib
from dataclasses import dataclass

from agent.agent import StructuredToolAgent, is_meaningful_verification


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    return_code: int


class FakeEnvironment:
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


# --- unit tests for the pure function ---

def test_is_meaningful_verification_blocklists_passive_commands():
    for cmd in [
        "cat script.sh",
        "ls -la",
        "chmod +x script.sh",
        "chown user file",
        "echo done",
        "pwd",
        "head -n 5 file.txt",
        "tail -f log.txt",
    ]:
        assert is_meaningful_verification(cmd) is False


def test_is_meaningful_verification_allows_everything_else():
    for cmd in [
        "python3 test.py",
        "pytest -q",
        "./a.out",
        "curl -s http://localhost/health",
        "diff a.txt b.txt",
        "python3 -c \"assert 1 == 1\"",
        "make test",
    ]:
        assert is_meaningful_verification(cmd) is True


# --- pending_verification gate (call site 1) ---

def test_chmod_after_edit_does_not_clear_pending_verification(monkeypatch):
    env = FakeEnvironment(exec_results=[FakeExecResult("", "", 0)])
    turns = [
        ("", [{"id": "c1", "name": "write_file", "arguments": {"path": "/app/script.sh", "content": "echo hi"}}]),
        ("", [{"id": "c2", "name": "terminal_exec", "arguments": {"command": "chmod +x /app/script.sh"}}]),
        ("", [{"id": "c3", "name": "task_complete", "arguments": {"evidence": "made it executable"}}]),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)
    # chmod alone must not count as verification -> nudge fires, then hard reject
    assert ctx.metadata["termination_reason"] == "completion_rejected_no_new_evidence"


def test_real_test_command_after_edit_clears_pending_verification(monkeypatch):
    env = FakeEnvironment(exec_results=[FakeExecResult("ok\n", "", 0)])
    turns = [
        ("", [{"id": "c1", "name": "write_file", "arguments": {"path": "/app/x.py", "content": "print(1)"}}]),
        ("", [{"id": "c2", "name": "terminal_exec", "arguments": {"command": "python3 test.py"}}]),
        ("", [{"id": "c3", "name": "task_complete", "arguments": {"evidence": "test passed"}}]),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)
    assert ctx.metadata["termination_reason"] == "task_complete"


# --- completion-evidence gate (call site 2) ---

def test_nudge_then_only_cat_readback_still_rejected(monkeypatch):
    env = FakeEnvironment(exec_results=[FakeExecResult("print(1)\n", "", 0)])
    turns = [
        ("", [{"id": "c1", "name": "write_file", "arguments": {"path": "/app/x.py", "content": "print(1)"}}]),
        ("", [{"id": "c2", "name": "task_complete", "arguments": {"evidence": "wrote it"}}]),  # nudged
        ("", [{"id": "c3", "name": "terminal_exec", "arguments": {"command": "cat /app/x.py"}}]),  # only a readback
        ("", [{"id": "c4", "name": "task_complete", "arguments": {"evidence": "read it back, looks right"}}]),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)
    assert ctx.metadata["termination_reason"] == "completion_rejected_no_new_evidence"


def test_nudge_then_real_test_command_accepted(monkeypatch):
    env = FakeEnvironment(exec_results=[FakeExecResult("ok\n", "", 0)])
    turns = [
        ("", [{"id": "c1", "name": "write_file", "arguments": {"path": "/app/x.py", "content": "print(1)"}}]),
        ("", [{"id": "c2", "name": "task_complete", "arguments": {"evidence": "wrote it"}}]),  # nudged
        ("", [{"id": "c3", "name": "terminal_exec", "arguments": {"command": "python3 /app/x.py"}}]),
        ("", [{"id": "c4", "name": "task_complete", "arguments": {"evidence": "ran it, exit 0"}}]),
    ]
    ctx = run_structured_agent(monkeypatch, env, turns)
    assert ctx.metadata["termination_reason"] == "task_complete"
