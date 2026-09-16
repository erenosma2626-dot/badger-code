"""v0.4.1 madde 1: cyclic_multi_target_loop detection + per-target
stuck_nudged flag, applied to StructuredToolAgent's tool-call code path.

Two related changes:
1. A third stuck-loop trigger (OR'd with the existing exact_repeat_stuck
   and target_is_stuck) that catches an agent cycling between N>=2
   distinct targets (A->B->C->D->A->B->C->D->...) for two full laps —
   observed in fix-code-vulnerability/build-cython-ext trials where 9-10
   files were cycled through for 100 turns with write_file never called.
2. stuck_nudged changes from a single global bool to a per-trigger-key
   set, so a nudge received for one target doesn't cause a hard
   termination the first time the agent struggles with a DIFFERENT,
   unrelated target (observed: sqlite C9NYKyU, EX92BKr).
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
    def __init__(self, results: list[FakeExecResult]):
        self._results = results
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
        return self._results[-1] if self._results else FakeExecResult(
            "__AGENT_CWD_AFTER__:/app\n", "", 0
        )


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


def run_structured_agent(monkeypatch, env, turns, max_turns=20):
    import agent.agent as agent_module

    monkeypatch.setattr(agent_module, "LLMClient", make_scripted_llm(turns))
    monkeypatch.setattr(agent_module, "MAX_TURNS", max_turns)

    sut = StructuredToolAgent(logs_dir=pathlib.Path("/tmp"), model_name="fake-model")
    ctx = FakeContext()
    asyncio.run(sut.run("do the thing", env, ctx))
    return ctx


def _read_call(i, path):
    return ("", [{"id": f"c{i}", "name": "read_file", "arguments": {"path": path}}])


def _exec_call(i, target):
    # A distinct command per target/attempt (varying grep pattern) so the
    # exact-repeat fingerprint never matches — isolates target-based and
    # cyclic signals from the exact-repeat one.
    return (
        "",
        [{"id": f"e{i}", "name": "terminal_exec", "arguments": {"command": f'grep -n "pattern_{i}" {target}'}}],
    )


# (a) 4 targets, 2 full cycles -> cyclic_multi_target_loop must fire.
def test_two_full_cycles_through_four_targets_triggers_cyclic_loop(monkeypatch):
    files = ["a.py", "b.py", "c.py", "d.py"] * 3  # plenty of turns available
    results = [FakeExecResult("", "not found", 1) for _ in files]
    env = FakeEnvironment(results)
    turns = [_read_call(i, f) for i, f in enumerate(files)]

    ctx = run_structured_agent(monkeypatch, env, turns)

    assert ctx.metadata["termination_reason"] == "stuck_loop_detected"
    assert ctx.metadata["turns"] < 20


# (b) only 1.5 cycles (6 distinct-target visits, not a full 2nd lap) ->
# must NOT trigger the cyclic signal (nor the other two, since no single
# target repeats 3x consecutively and no command text repeats exactly).
def test_one_and_a_half_cycles_does_not_trigger_cyclic_loop(monkeypatch):
    files = ["a.py", "b.py", "c.py", "d.py", "a.py", "b.py"]
    results = [FakeExecResult("", "not found", 1) for _ in files]
    env = FakeEnvironment(results)
    turns = [_read_call(i, f) for i, f in enumerate(files)] + [
        ("", [{"id": "done", "name": "task_complete", "arguments": {"evidence": "done"}}])
    ]

    ctx = run_structured_agent(monkeypatch, env, turns, max_turns=10)

    assert ctx.metadata["termination_reason"] != "stuck_loop_detected"


# (c) nudge received for target X, then a FIRST unproductive attempt at a
# DIFFERENT target Y -> must nudge again (not hard-terminate), proving
# stuck_nudged is now per-target rather than a single global flag.
def test_nudge_on_one_target_then_first_trouble_on_another_gets_a_new_nudge_not_hard_terminate(monkeypatch):
    # 3 unproductive attempts on "x.py" trip target_is_stuck -> nudge #1
    # (key "x.py"). Then 3 unproductive attempts on a DIFFERENT "y.py"
    # should trip target_is_stuck again for a NEW key -> nudge #2, not a
    # hard terminate on the very first y.py attempt.
    files = ["x.py", "x.py", "x.py", "y.py", "y.py", "y.py"]
    results = [FakeExecResult("", "", 1) for _ in files]
    env = FakeEnvironment(results)
    turns = [_exec_call(i, f) for i, f in enumerate(files)] + [
        ("", [{"id": "done", "name": "task_complete", "arguments": {"evidence": "done"}}])
    ]

    ctx = run_structured_agent(monkeypatch, env, turns, max_turns=10)

    assert ctx.metadata["termination_reason"] != "stuck_loop_detected"


# Dedicated test proving the cyclic signal fires on its own, isolated from
# the other two: varying commands each turn (defeats exact_repeat_stuck)
# and exit_code=0/no-unproductive-keyword output each turn (defeats
# target_is_stuck, since target_attempt_counts never accumulates) — only
# the cross-target cycling pattern itself should trip stuck_loop_detected.
def test_cyclic_signal_alone_triggers_when_neither_other_signal_would(monkeypatch):
    # 3 full laps: laps 1+2 trip the cyclic nudge (turn 8), lap 3 repeats
    # the same cycle key after the nudge -> hard terminate.
    files = ["a.py", "b.py", "c.py", "d.py"] * 3
    results = [FakeExecResult("looked, nothing changed\n", "", 0) for _ in files]
    env = FakeEnvironment(results)
    turns = [_exec_call(i, f) for i, f in enumerate(files)]

    ctx = run_structured_agent(monkeypatch, env, turns, max_turns=15)

    assert ctx.metadata["termination_reason"] == "stuck_loop_detected"


def test_ten_targets_cyclic_loop_triggers_stuck_loop_with_window_44(monkeypatch):
    # Real-world fix-code-vulnerability scenario: 10 targets cycled through.
    # With CYCLIC_LOOP_WINDOW=44, laps 1+2 (20 turns) trip cyclic nudge,
    # and lap 3 repeats the cycle key triggering hard termination at turn 30.
    targets = [f"file{i}.py" for i in range(10)]
    files = targets * 3
    results = [FakeExecResult("looked, nothing changed\n", "", 0) for _ in files]
    env = FakeEnvironment(results)
    turns = [_exec_call(i, f) for i, f in enumerate(files)] + [
        ("", [{"id": "done", "name": "task_complete", "arguments": {"evidence": "done"}}])
    ]

    ctx = run_structured_agent(monkeypatch, env, turns, max_turns=35)

    assert ctx.metadata["termination_reason"] == "stuck_loop_detected"
    assert ctx.metadata["turns"] == 30



# (d) regression: existing exact-repeat and same-target stuck-loop tests

# must still pass — covered by test_structured_agent_stuck_loop.py, run
# together with this file as part of the full suite.
