"""Tests for the structured tool-calling primitives (agent/structured_tools.py),
the "next target architecture" from docs/plan.md: terminal_exec, write_file,
read_file each return a deterministic ExecutionReceipt instead of text the
model has to interpret. Uses a FakeEnvironment, same style as
tests/test_tools_write_file.py — never talks to a real container.
"""

import asyncio
import base64
from dataclasses import dataclass

from agent.structured_tools import (
    TOOL_SCHEMAS,
    get_stored_output,
    read_file,
    terminal_exec,
    write_file,
)


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    return_code: int


class FakeEnvironment:
    def __init__(self, stdout: str = "", stderr: str = "", return_code: int = 0):
        self.last_command: str | None = None
        self._stdout = stdout
        self._stderr = stderr
        self._return_code = return_code

    async def exec(self, command: str, timeout_sec: int) -> FakeExecResult:
        self.last_command = command
        return FakeExecResult(self._stdout, self._stderr, self._return_code)


def test_tool_schemas_declare_all_four_tools_with_required_params():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"terminal_exec", "write_file", "read_file", "task_complete"}
    by_name = {t["function"]["name"]: t["function"] for t in TOOL_SCHEMAS}
    assert by_name["terminal_exec"]["parameters"]["required"] == ["command"]
    assert set(by_name["write_file"]["parameters"]["required"]) == {"path", "content"}
    assert by_name["read_file"]["parameters"]["required"] == ["path"]
    assert by_name["task_complete"]["parameters"]["required"] == ["evidence"]


def test_terminal_exec_parses_cwd_after_and_exit_code():
    env = FakeEnvironment(
        stdout="hello\n__AGENT_CWD_AFTER__:/app/src\n./a.py\n./b.py\n",
        return_code=0,
    )
    receipt = asyncio.run(terminal_exec(env, "echo hello", timeout_sec=30))
    assert receipt.tool == "terminal_exec"
    assert receipt.exit_code == 0
    assert receipt.cwd_after == "/app/src"
    assert "hello" in receipt.stdout_tail
    assert receipt.changed_paths == ["./a.py", "./b.py"]
    assert receipt.output_ref is not None
    assert "hello" in get_stored_output(receipt.output_ref)


def test_terminal_exec_reports_nonzero_exit_code():
    env = FakeEnvironment(
        stdout="__AGENT_CWD_AFTER__:/app\n", stderr="boom", return_code=1
    )
    receipt = asyncio.run(terminal_exec(env, "false", timeout_sec=30))
    assert receipt.exit_code == 1
    assert "boom" in receipt.stderr_tail


def test_write_file_receipt_reports_success_and_changed_path():
    env = FakeEnvironment(stdout="WRITE_OK\n", return_code=0)
    receipt = asyncio.run(write_file(env, "/tmp/x.txt", "hi", timeout_sec=30))
    assert receipt.tool == "write_file"
    assert receipt.exit_code == 0
    assert receipt.changed_paths == ["/tmp/x.txt"]
    assert receipt.content_bytes == len("hi".encode("utf-8"))


def test_write_file_does_not_leak_dangerous_path_into_command():
    env = FakeEnvironment(stdout="WRITE_OK\n", return_code=0)
    dangerous = "/tmp/it's a $(danger).txt"
    asyncio.run(write_file(env, dangerous, "x", timeout_sec=30))
    assert dangerous not in env.last_command


def test_read_file_decodes_base64_roundtrip():
    content = "line1\nline2 café\n"
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    env = FakeEnvironment(stdout=b64, return_code=0)
    receipt = asyncio.run(read_file(env, "/tmp/f.txt", timeout_sec=30))
    assert receipt.exit_code == 0
    assert receipt.stdout_tail == content
    assert get_stored_output(receipt.output_ref) == content


def test_read_file_reports_failure_on_nonzero_exit():
    env = FakeEnvironment(stdout="", stderr="No such file", return_code=1)
    receipt = asyncio.run(read_file(env, "/tmp/missing.txt", timeout_sec=30))
    assert receipt.exit_code == 1
    assert "No such file" in receipt.stderr_tail
