"""Tests for the completion-evidence gate (v0.4 spec §2.1, tightened):
when the agent declares TASK_COMPLETE with verification_status
missing/stale, the first attempt is rejected with a nudge. The SECOND
attempt is only accepted if a genuine NEW tool-call (write_file or a shell
command, regardless of its outcome) happened since the nudge — a bare
text response that re-declares done is rejected HARD (terminates the
episode, not another nudge, so there is no infinite-loop risk). This
tightening closes the "yüzeysel öz-doğrulama" gap from the
log-summary-date-ranges trial (docs/plan.md): the old gate accepted a
second TASK_COMPLETE unconditionally even when nothing but narrative
happened in between. The nudge/retry state must still be per-episode (a
fresh BaselineAgent.run() call must not remember the previous episode's
nudge state).
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
    rejected: the loop must NOT terminate on turn 2, and a genuine action
    (a shell command) before the next TASK_COMPLETE is what lets the run
    terminate as accepted rather than hard-rejected."""
    env = FakeEnvironment()
    # Turn 1: edit the file (verification_status becomes "missing").
    # Turn 2: declare TASK_COMPLETE while still missing -> rejected (nudged).
    # Turn 3: a genuine action since the nudge (§2.1 tightened gate).
    # Turn 4: TASK_COMPLETE again -> accepted (evidence of an attempt exists).
    llm_script = [
        WRITE_BLOCK,
        "TASK_COMPLETE",
        "```bash\ncat /app/solution.py\n```",
        "TASK_COMPLETE",
    ]

    context = run_agent(env, llm_script, max_turns=20)

    # It must have taken more than 2 turns (turn 2's TASK_COMPLETE was
    # rejected, forcing further turns) to finish.
    assert context.metadata["turns"] >= 3
    assert context.metadata["termination_reason"] == "task_complete"


def test_second_task_complete_with_no_new_action_since_nudge_is_rejected_hard():
    """(b, tightened) A second TASK_COMPLETE that follows the nudge with NO
    new tool-call in between (just re-declaring done) must be rejected
    HARD — the episode terminates without accepting completion, and
    without a third nudge (no infinite-loop risk)."""
    env = FakeEnvironment()
    llm_script = [WRITE_BLOCK, "TASK_COMPLETE", "TASK_COMPLETE"]

    context = run_agent(env, llm_script, max_turns=20)

    assert context.metadata["termination_reason"] == "completion_rejected_no_new_evidence"
    assert context.metadata["finished"] is not True
    assert context.metadata["verification_status"] == "missing"
    # 3 turns: edit, rejected (nudged) TASK_COMPLETE, hard-rejected TASK_COMPLETE.
    assert context.metadata["turns"] == 3


def test_second_task_complete_is_accepted_when_a_new_action_happened_since_the_nudge():
    """(c) If the model takes ANY genuine action after the nudge — even an
    inspect command that doesn't actually pass verification — before
    re-declaring done, that declaration is accepted (soft-block): the gate
    requires evidence of an attempt, not proof of a passing test."""
    env = FakeEnvironment()
    llm_script = [
        WRITE_BLOCK,
        "TASK_COMPLETE",
        "```bash\ncat /app/solution.py\n```",
        "TASK_COMPLETE",
    ]

    context = run_agent(env, llm_script, max_turns=20)

    assert context.metadata["termination_reason"] == "task_complete"
    assert context.metadata["finished"] is True


def test_nudge_counter_is_per_episode_not_global():
    """Running two separate episodes back-to-back on fresh agent instances:
    the second episode must ALSO get one rejection (and, with no new
    action taken, the same hard rejection) — the nudge-once state and the
    action-since-nudge flag must not leak from the first run() call."""
    env1 = FakeEnvironment()
    llm_script = [WRITE_BLOCK, "TASK_COMPLETE", "TASK_COMPLETE"]
    context1 = run_agent(env1, llm_script, max_turns=20)
    assert context1.metadata["turns"] == 3
    assert context1.metadata["termination_reason"] == "completion_rejected_no_new_evidence"

    env2 = FakeEnvironment()
    context2 = run_agent(env2, llm_script, max_turns=20)
    assert context2.metadata["turns"] == 3
    assert context2.metadata["termination_reason"] == "completion_rejected_no_new_evidence"
