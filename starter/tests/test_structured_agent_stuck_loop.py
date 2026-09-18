"""Evidence-based stuck-loop detection ported to StructuredToolAgent
(v0.4 spec §1.1 madde 2 + §2.3): applies to terminal_exec/read_file calls.
Two triggers: (a) exact repeat of tool+command/path+exit_code+output, (b)
N unproductive attempts against the same extracted target even when the
command text varies each turn. Mirrors tests/test_agent_stuck_loop.py's
style for BaselineAgent.
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
    """Bootstrap call always succeeds; scripted results consumed in order
    for subsequent (non-bootstrap) exec() calls."""

    def __init__(self, results: list[FakeExecResult]):
        self._results = results
        self._idx = 0
        self.calls: list[str] = []

    async def exec(self, command: str, timeout_sec: int) -> FakeExecResult:
        self.calls.append(command)
        if "__AGENT_CWD_AFTER__" not in command:
            if "WRITE_OK" in command or "python3" in command or "base64" in command:
                return FakeExecResult("WRITE_OK\n", "", 0)
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


def test_identical_terminal_exec_repeated_triggers_stuck_loop(monkeypatch):
    results = [FakeExecResult("connection refused\n", "", 1) for _ in range(10)]
    env = FakeEnvironment(results)
    turns = [
        (
            "",
            [{"id": f"c{i}", "name": "terminal_exec", "arguments": {"command": "curl -s http://localhost:8080/health"}}],
        )
        for i in range(10)
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    assert ctx.metadata["termination_reason"] == "stuck_loop_detected"
    assert ctx.metadata["turns"] < 20


def test_retry_with_changing_terminal_exec_outcome_is_not_flagged_as_stuck(monkeypatch):
    results = [
        FakeExecResult("curl: connection refused\n", "", 7),
        FakeExecResult("curl: connection refused\n", "", 7),
        FakeExecResult("curl: (52) empty reply\n", "", 52),
        FakeExecResult("HTTP/1.1 200 OK\n", "", 0),
    ]
    env = FakeEnvironment(results)
    turns = [
        ("", [{"id": "c0", "name": "terminal_exec", "arguments": {"command": "curl -s http://x/health"}}]),
        ("", [{"id": "c1", "name": "terminal_exec", "arguments": {"command": "curl -s http://x/health"}}]),
        ("", [{"id": "c2", "name": "terminal_exec", "arguments": {"command": "curl -s http://x/health"}}]),
        ("", [{"id": "c3", "name": "terminal_exec", "arguments": {"command": "curl -s http://x/health"}}]),
        ("", [{"id": "c4", "name": "task_complete", "arguments": {"evidence": "200 OK"}}]),
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    assert ctx.metadata["termination_reason"] != "stuck_loop_detected"
    assert ctx.metadata["termination_reason"] == "task_complete"


def test_varying_read_file_path_never_repeats_but_same_target_still_triggers(monkeypatch):
    """§2.3 — a model that keeps read_file-ing the SAME missing path is an
    exact repeat too (path never varies), confirming the target-based
    signal also covers read_file's simplest case."""
    results = [FakeExecResult("", "No such file or directory", 1) for _ in range(6)]
    env = FakeEnvironment(results)
    turns = [
        ("", [{"id": f"c{i}", "name": "read_file", "arguments": {"path": "/app/missing.py"}}])
        for i in range(6)
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    assert ctx.metadata["termination_reason"] == "stuck_loop_detected"
    assert ctx.metadata["turns"] < 20


def test_varying_terminal_exec_command_against_same_target_triggers_stuck_loop(monkeypatch):
    """§2.3 — the fix-code-vulnerability pattern applied to
    StructuredToolAgent: the model varies its grep pattern each turn but
    never gets a hit against the same file, so the exact-repeat fingerprint
    never fires but the same-target signal must."""
    results = [FakeExecResult("", "", 1) for _ in range(6)]
    env = FakeEnvironment(results)
    turns = [
        (
            "",
            [{"id": f"c{i}", "name": "terminal_exec", "arguments": {"command": f'grep -n "pattern_{i}" src/app.py'}}],
        )
        for i in range(6)
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    assert ctx.metadata["termination_reason"] == "stuck_loop_detected"
    assert ctx.metadata["turns"] < 20


def test_identical_write_file_repeated_triggers_stuck_loop(monkeypatch):
    """v0.5.2 fix 1: write_file repeating the exact same path and content
    must trigger stuck-loop detection rather than looping indefinitely."""
    env = FakeEnvironment([])
    turns = [
        (
            "",
            [
                {
                    "id": f"c{i}",
                    "name": "write_file",
                    "arguments": {
                        "path": "/app/regex.txt",
                        "content": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                    },
                }
            ],
        )
        for i in range(10)
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    assert ctx.metadata["termination_reason"] == "stuck_loop_detected"
    assert ctx.metadata["turns"] < 20


def test_varying_content_write_file_does_not_trigger_exact_repeat(monkeypatch):
    """v0.5.2 fix 1: editing the same file with DIFFERENT content is progress
    and must not be flagged as an exact-repeat stuck loop."""
    env = FakeEnvironment([])
    turns = [
        (
            "",
            [
                {
                    "id": f"c{i}",
                    "name": "write_file",
                    "arguments": {
                        "path": "/app/script.py",
                        "content": f"# attempt {i}\nprint({i})\n",
                    },
                }
            ],
        )
        for i in range(4)
    ] + [
        (
            "",
            [
                {
                    "id": "c_verify",
                    "name": "terminal_exec",
                    "arguments": {"command": "python3 /app/script.py"},
                }
            ],
        ),
        (
            "",
            [
                {
                    "id": "c_done",
                    "name": "task_complete",
                    "arguments": {"evidence": "python3 script.py passed"},
                }
            ],
        ),
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    assert ctx.metadata["termination_reason"] != "stuck_loop_detected"
    assert ctx.metadata["termination_reason"] == "task_complete"


def test_sequential_append_calls_with_different_content_do_not_trigger_stuck_or_cyclic_loop(monkeypatch):
    """v0.5.3: Appending different chunks to the same file (initial write + multiple appends)
    is progress (file grows, hashes differ) and must NOT trigger exact-repeat, target-stuck,
    or cyclic-loop detection."""
    env = FakeEnvironment([])
    # 1 initial write + 4 append chunks = 5 sequential writes to the same file
    turns = [
        (
            "",
            [
                {
                    "id": "c0",
                    "name": "write_file",
                    "arguments": {
                        "path": "/app/large_module.py",
                        "content": "# Part 0: header and imports\nimport sys\n",
                        "append": False,
                    },
                }
            ],
        )
    ] + [
        (
            "",
            [
                {
                    "id": f"c{i}",
                    "name": "write_file",
                    "arguments": {
                        "path": "/app/large_module.py",
                        "content": f"# Part {i}: function def {i}\ndef func_{i}(): return {i}\n",
                        "append": True,
                    },
                }
            ],
        )
        for i in range(1, 5)
    ] + [
        (
            "",
            [
                {
                    "id": "c_verify",
                    "name": "terminal_exec",
                    "arguments": {"command": "python3 -c 'import large_module'"},
                }
            ],
        ),
        (
            "",
            [
                {
                    "id": "c_done",
                    "name": "task_complete",
                    "arguments": {"evidence": "large_module imported clean"},
                }
            ],
        ),
    ]

    ctx = run_structured_agent(monkeypatch, env, turns, max_turns=15)

    assert ctx.metadata["termination_reason"] != "stuck_loop_detected"
    assert ctx.metadata["termination_reason"] == "task_complete"


def test_identical_append_calls_repeated_still_trigger_exact_repeat_stuck_loop(monkeypatch):
    """v0.5.3: Appending the EXACT same content chunk repeatedly to the same file
    means the agent is stuck in an append loop — exact-repeat detector must catch it."""
    env = FakeEnvironment([])
    turns = [
        (
            "",
            [
                {
                    "id": f"c{i}",
                    "name": "write_file",
                    "arguments": {
                        "path": "/app/file.txt",
                        "content": "identical chunk\n",
                        "append": True,
                    },
                }
            ],
        )
        for i in range(5)
    ]

    ctx = run_structured_agent(monkeypatch, env, turns, max_turns=10)

    assert ctx.metadata["termination_reason"] == "stuck_loop_detected"

