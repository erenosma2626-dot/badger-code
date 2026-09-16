"""v0.4.1 madde 1: cyclic_multi_target_loop detection + per-target
stuck_nudged flag, applied to BaselineAgent's shell code path (mirrors
test_structured_agent_cyclic_loop.py's coverage for StructuredToolAgent).
"""

import asyncio
from dataclasses import dataclass, field

import agent.agent as agent_module
from agent.agent import BaselineAgent


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    return_code: int


class FakeEnvironment:
    def __init__(self, results: list[FakeExecResult]):
        self._results = results
        self.calls: list[str] = []

    async def exec(self, command: str, timeout_sec: int) -> FakeExecResult:
        self.calls.append(command)
        idx = len(self.calls) - 1
        if idx < len(self._results):
            return self._results[idx]
        return self._results[-1]


class FakeLLMClient:
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


def _bash(cmd: str) -> str:
    return f"```bash\n{cmd}\n```"


# (a) cyclic signal alone: varying commands, exit 0/no-unproductive output
# each time (defeats both exact-repeat and same-target), 3 full laps
# through 4 targets -> nudge on lap 2, hard-terminate on lap 3 repeat.
def test_cyclic_signal_alone_triggers_stuck_loop():
    files = ["a.py", "b.py", "c.py", "d.py"] * 3
    results = [FakeExecResult("ok\n", "", 0)]  # bootstrap
    results += [FakeExecResult("looked, nothing changed\n", "", 0) for _ in files]
    env = FakeEnvironment(results)
    llm_script = [_bash(f'grep -n "pattern_{i}" {f}') for i, f in enumerate(files)]

    context = run_agent(env, llm_script, max_turns=15)

    assert context.metadata["termination_reason"] == "stuck_loop_detected"


# (b) only 1.5 cycles -> must not trigger.
def test_one_and_a_half_cycles_does_not_trigger_cyclic_loop():
    files = ["a.py", "b.py", "c.py", "d.py", "a.py", "b.py"]
    results = [FakeExecResult("ok\n", "", 0)]  # bootstrap
    results += [FakeExecResult("looked, nothing changed\n", "", 0) for _ in files]
    env = FakeEnvironment(results)
    llm_script = [_bash(f'grep -n "pattern_{i}" {f}') for i, f in enumerate(files)] + [
        "TASK_COMPLETE"
    ]

    context = run_agent(env, llm_script, max_turns=10)

    assert context.metadata["termination_reason"] != "stuck_loop_detected"


# (c) nudge on target x.py, then a first unproductive attempt on a
# DIFFERENT y.py -> must nudge again, not hard-terminate (per-target flag).
def test_nudge_on_one_target_then_first_trouble_on_another_gets_a_new_nudge():
    files = ["x.py", "x.py", "x.py", "y.py", "y.py", "y.py"]
    results = [FakeExecResult("ok\n", "", 0)]  # bootstrap
    results += [FakeExecResult("", "", 1) for _ in files]
    env = FakeEnvironment(results)
    llm_script = [_bash(f'grep -n "pattern_{i}" {f}') for i, f in enumerate(files)] + [
        "TASK_COMPLETE"
    ]

    context = run_agent(env, llm_script, max_turns=10)

    assert context.metadata["termination_reason"] != "stuck_loop_detected"
