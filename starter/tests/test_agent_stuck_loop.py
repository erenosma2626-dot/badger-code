"""Tests for evidence-based stuck-loop detection in the agent's main loop.

Stuck-loop detection must trigger only when a command's *outcome* repeats
(same command, same exit code, same output) — never merely because the same
command text was retried. A legitimate retry/poll (e.g. curling a server
until it's up) produces different exit codes/output each time and must be
allowed to continue up to the turn budget, not be cut off as "stuck".
"""

import asyncio
from dataclasses import dataclass, field

import pytest

import agent.agent as agent_module
from agent.agent import BaselineAgent


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    return_code: int


class FakeEnvironment:
    """Runs a scripted sequence of results keyed by call order, ignoring
    the actual command text (the agent module bootstraps with a fixed
    `pwd && ls -la ...` command before turn 1, so scripted results start
    after that call)."""

    def __init__(self, results: list[FakeExecResult]):
        self._results = results
        self.calls: list[str] = []

    async def exec(self, command: str, timeout_sec: int) -> FakeExecResult:
        self.calls.append(command)
        idx = len(self.calls) - 1
        if idx < len(self._results):
            return self._results[idx]
        # Repeat the last scripted result once the script runs out.
        return self._results[-1]


class FakeLLMClient:
    """Replaces agent.llm.LLMClient: returns a scripted list of assistant
    responses, one per call to chat(), then repeats the last one."""

    def __init__(self, model_name: str | None = None):
        pass

    async def chat(self, messages: list[dict]) -> tuple[str, dict]:
        idx = self._next_idx
        self._next_idx += 1
        if idx < len(self._script):
            return self._script[idx], {}
        return self._script[-1], {}


def make_fake_llm(script: list[str]):
    class _Client(FakeLLMClient):
        _script = script
        _next_idx = 0

    return _Client


@dataclass
class FakeContext:
    n_input_tokens: int = 0
    n_output_tokens: int = 0
    metadata: dict = field(default_factory=dict)


SAME_CMD = "curl -s http://localhost:8080/health"
BASH_BLOCK = f"```bash\n{SAME_CMD}\n```"


def run_agent(env: FakeEnvironment, llm_script: list[str], max_turns: int = 20):
    original_client = agent_module.LLMClient
    original_max_turns = agent_module.MAX_TURNS
    agent_module.LLMClient = make_fake_llm(llm_script)
    agent_module.MAX_TURNS = max_turns
    try:
        import logging
        import pathlib

        agent = BaselineAgent(logs_dir=pathlib.Path("/tmp"), model_name="fake-model")
        agent.logger = logging.getLogger("test")
        context = FakeContext()
        asyncio.run(agent.run("do the thing", env, context))
        return context
    finally:
        agent_module.LLMClient = original_client
        agent_module.MAX_TURNS = original_max_turns


def test_identical_command_exit_code_and_output_triggers_stuck_loop():
    """(a) Same command + same exit code + same output, repeated → the
    stuck-loop guard must fire before max_turns is reached."""
    # Bootstrap call (turn 0, not scripted per-turn) + repeated identical calls.
    results = [FakeExecResult("ok\n", "", 0)] + [
        FakeExecResult("connection refused\n", "", 1) for _ in range(10)
    ]
    env = FakeEnvironment(results)
    llm_script = [BASH_BLOCK] * 10

    context = run_agent(env, llm_script, max_turns=20)

    assert context.metadata["termination_reason"] == "stuck_loop_detected"
    assert context.metadata["turns"] < 20


def test_retry_with_changing_outcome_is_not_flagged_as_stuck():
    """(b) Same command text, but exit code/output change each call (e.g. a
    server coming up) → must NOT be treated as a stuck loop; the agent
    should be able to keep polling up to the turn budget."""
    results = [FakeExecResult("ok\n", "", 0)]  # bootstrap
    # Same command text every time, but outcome differs each call: refused,
    # refused, refused, then finally 200 OK.
    results += [
        FakeExecResult("curl: connection refused\n", "", 7),
        FakeExecResult("curl: connection refused\n", "", 7),
        FakeExecResult("curl: (52) empty reply\n", "", 52),
        FakeExecResult("HTTP/1.1 200 OK\n", "", 0),
    ]
    env = FakeEnvironment(results)
    llm_script = [BASH_BLOCK, BASH_BLOCK, BASH_BLOCK, BASH_BLOCK, "TASK_COMPLETE"]

    context = run_agent(env, llm_script, max_turns=20)

    assert context.metadata["termination_reason"] != "stuck_loop_detected"
