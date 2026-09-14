"""Tests for the completion-evidence soft-gate: when the agent declares
TASK_COMPLETE with verification_status missing/stale, the first attempt
must be rejected (loop continues) and only the SECOND attempt is accepted
— even if verification is still missing/stale. This must never turn into
a hard block or an infinite nudge loop, and the retry counter must be
per-episode (a fresh BaselineAgent.run() call must not remember the
previous episode's nudge state).
"""

import asyncio
import logging
import pathlib
from dataclasses import dataclass, field

import agent.agent as agent_module
from agent.agent import BaselineAgent


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    return_code: int


class FakeEnvironment:
    def __init__(self, default: FakeExecResult = FakeExecResult("ok\n", "", 0)):
        self._default = default
        self.calls: list[str] = []

    async def exec(self, command: str, timeout_sec: int) -> FakeExecResult:
        self.calls.append(command)
        return self._default


class FakeLLMClient:
    def __init__(self, model_name: str | None = None):
        pass

    async def chat(self, messages: list[dict]) -> tuple[str, dict]:
        idx = getattr(self, "_next_idx", 0)
        self._next_idx = idx + 1
        script = self._script
        if idx < len(script):
            return script[idx], {}
        return script[-1], {}


def make_fake_llm(script: list[str]):
    class _Client(FakeLLMClient):
        _script = script

    return _Client


@dataclass
class FakeContext:
    n_input_tokens: int = 0
    n_output_tokens: int = 0
    metadata: dict = field(default_factory=dict)


def run_agent(env: FakeEnvironment, llm_script: list[str], max_turns: int = 20):
    original_client = agent_module.LLMClient
    original_max_turns = agent_module.MAX_TURNS
    agent_module.LLMClient = make_fake_llm(llm_script)
    agent_module.MAX_TURNS = max_turns
    try:
        agent = BaselineAgent(logs_dir=pathlib.Path("/tmp"), model_name="fake-model")
        agent.logger = logging.getLogger("test")
        context = FakeContext()
        asyncio.run(agent.run("do the thing", env, context))
        return context
    finally:
        agent_module.LLMClient = original_client
        agent_module.MAX_TURNS = original_max_turns


WRITE_BLOCK = "```write_file:/app/solution.py\nprint('hi')\n```"


def test_first_task_complete_with_missing_evidence_is_rejected_and_loop_continues():
    """(a) An edit with no verification since → first TASK_COMPLETE must be
    rejected: the loop must NOT terminate, and the next scripted turn
    (also TASK_COMPLETE) is what actually needs to run."""
    env = FakeEnvironment()
    # Turn 1: edit the file (verification_status becomes "missing").
    # Turn 2: declare TASK_COMPLETE while still missing -> must be rejected.
    # Turn 3: LLM never gets to run because we only assert the loop kept
    # going past turn 2 without terminating on it. Give a 3rd scripted turn
    # that just declares complete again so the run terminates deterministically.
    llm_script = [WRITE_BLOCK, "TASK_COMPLETE", "TASK_COMPLETE"]

    context = run_agent(env, llm_script, max_turns=20)

    # It must have taken more than 2 turns (turn 2's TASK_COMPLETE was
    # rejected, forcing a 3rd turn) to finish.
    assert context.metadata["turns"] >= 3
    assert context.metadata["termination_reason"] == "task_complete"


def test_second_task_complete_is_accepted_even_if_still_missing():
    """(b) Even though verification_status is still 'missing' on the second
    TASK_COMPLETE, it must be accepted (soft-block, not hard-fail) — no
    infinite nudge loop."""
    env = FakeEnvironment()
    llm_script = [WRITE_BLOCK, "TASK_COMPLETE", "TASK_COMPLETE"]

    context = run_agent(env, llm_script, max_turns=20)

    assert context.metadata["termination_reason"] == "task_complete"
    assert context.metadata["verification_status"] == "missing"
    # Exactly 3 turns: edit, rejected TASK_COMPLETE, accepted TASK_COMPLETE.
    assert context.metadata["turns"] == 3


def test_nudge_counter_is_per_episode_not_global():
    """Running two separate episodes back-to-back on fresh agent instances:
    the second episode must ALSO get one rejection before acceptance — the
    nudge-once state must not leak from the first run() call."""
    env1 = FakeEnvironment()
    llm_script = [WRITE_BLOCK, "TASK_COMPLETE", "TASK_COMPLETE"]
    context1 = run_agent(env1, llm_script, max_turns=20)
    assert context1.metadata["turns"] == 3

    env2 = FakeEnvironment()
    context2 = run_agent(env2, llm_script, max_turns=20)
    assert context2.metadata["turns"] == 3
    assert context2.metadata["termination_reason"] == "task_complete"
