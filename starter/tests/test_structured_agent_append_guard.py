"""Tests for the v0.5.3 write_file append guardrail (agent.py):

Guards against accidental append=True calls appending to pre-existing or
uninitialized files on disk without blocking the execution.
- (a) path initialized with append=false (or default) -> subsequent append=true has NO warning.
- (b) path pre-existed on disk, agent calls append=true directly without append=false -> warning PRESENT.
- (c) subsequent append=true to the same uninitialized path -> NO warning (warn once per path).
"""

import asyncio
import json
import pathlib
from dataclasses import dataclass

import pytest

from agent.agent import StructuredToolAgent


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    return_code: int


class FakeEnvironment:
    async def exec(self, command: str, timeout_sec: int) -> FakeExecResult:
        return FakeExecResult("__AGENT_CWD_AFTER__:/app\nWRITE_OK\n", "", 0)


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


def test_uninitialized_path_append_true_receives_warning(monkeypatch):
    """(b) path session dışından zaten vardı, agent hiç append=false yapmadan
    direkt append=true çağırdı -> uyarı VAR, yazma yine de gerçekleşti."""
    env = FakeEnvironment()
    target_path = "/app/preexisting.txt"
    turns = [
        (
            "",
            [
                {
                    "id": "c1",
                    "name": "write_file",
                    "arguments": {"path": target_path, "content": "chunk 1\n", "append": True},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
        (
            "",
            [
                {
                    "id": "c2",
                    "name": "task_complete",
                    "arguments": {"evidence": "done"},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    tool_msgs = [m for m in ctx.metadata["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) >= 1
    first_tool_data = json.loads(tool_msgs[0]["content"])

    expected_warning = (
        f"Note: '{target_path}' was not created by you with append=false in this "
        "session (it may have pre-existed on disk). Content was appended to its "
        "existing content, not overwritten. If you intended to start a NEW file, "
        "call write_file with append=false first."
    )

    assert "warning" in first_tool_data
    assert first_tool_data["warning"] == expected_warning
    assert expected_warning in tool_msgs[0]["content"]


def test_initialized_path_append_false_then_append_true_receives_no_warning(monkeypatch):
    """(a) path hiç yoktu, append=false ile yazıldı -> set'e eklendi,
    sonraki append=true'da uyarı YOK."""
    env = FakeEnvironment()
    target_path = "/app/new_file.txt"
    turns = [
        (
            "",
            [
                {
                    "id": "c1",
                    "name": "write_file",
                    "arguments": {"path": target_path, "content": "chunk 1\n", "append": False},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
        (
            "",
            [
                {
                    "id": "c2",
                    "name": "write_file",
                    "arguments": {"path": target_path, "content": "chunk 2\n", "append": True},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
        (
            "",
            [
                {
                    "id": "c3",
                    "name": "task_complete",
                    "arguments": {"evidence": "done"},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    tool_msgs = [m for m in ctx.metadata["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) >= 2

    # Second tool call is append=True on an initialized path -> NO warning
    second_tool_data = json.loads(tool_msgs[1]["content"])
    assert "was not created by you with append=false" not in tool_msgs[1]["content"]
    assert second_tool_data.get("warning") is None


def test_uninitialized_path_warns_only_once_on_repeated_append_true(monkeypatch):
    """(c) aynı 'sahipsiz' path'e ikinci kez append=true çağrılırsa ->
    artık uyarı YOK (ilk çağrıda sete eklendiği için)."""
    env = FakeEnvironment()
    target_path = "/app/unclaimed.txt"
    turns = [
        (
            "",
            [
                {
                    "id": "c1",
                    "name": "write_file",
                    "arguments": {"path": target_path, "content": "part 1\n", "append": True},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
        (
            "",
            [
                {
                    "id": "c2",
                    "name": "write_file",
                    "arguments": {"path": target_path, "content": "part 2\n", "append": True},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
        (
            "",
            [
                {
                    "id": "c3",
                    "name": "task_complete",
                    "arguments": {"evidence": "done"},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    tool_msgs = [m for m in ctx.metadata["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) >= 2

    first_tool_data = json.loads(tool_msgs[0]["content"])
    second_tool_data = json.loads(tool_msgs[1]["content"])

    # First call: warning present
    assert "warning" in first_tool_data
    assert "was not created by you with append=false" in first_tool_data["warning"]

    # Second call: NO warning
    assert "was not created by you with append=false" not in tool_msgs[1]["content"]
    assert second_tool_data.get("warning") is None


def test_initialized_path_omitted_append_param_then_append_true_receives_no_warning(monkeypatch):
    """Default append=False (parametre verilmeden) yazıldı -> set'e eklendi,
    sonraki append=true'da uyarı YOK."""
    env = FakeEnvironment()
    target_path = "/app/default_param.txt"
    turns = [
        (
            "",
            [
                {
                    "id": "c1",
                    "name": "write_file",
                    "arguments": {"path": target_path, "content": "initial\n"},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
        (
            "",
            [
                {
                    "id": "c2",
                    "name": "write_file",
                    "arguments": {"path": target_path, "content": "appended\n", "append": True},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
        (
            "",
            [
                {
                    "id": "c3",
                    "name": "task_complete",
                    "arguments": {"evidence": "done"},
                }
            ],
            {"prompt_tokens": 1, "completion_tokens": 1},
        ),
    ]

    ctx = run_structured_agent(monkeypatch, env, turns)

    tool_msgs = [m for m in ctx.metadata["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) >= 2

    second_tool_data = json.loads(tool_msgs[1]["content"])
    assert "was not created by you with append=false" not in tool_msgs[1]["content"]
    assert second_tool_data.get("warning") is None
