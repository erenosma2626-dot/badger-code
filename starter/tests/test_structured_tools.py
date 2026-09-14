"""Tests for the structured tool-calling primitives (agent/structured_tools.py),
the "next target architecture" from docs/plan.md: terminal_exec, write_file,
read_file each return a deterministic ExecutionReceipt instead of text the
model has to interpret. Uses a FakeEnvironment, same style as
tests/test_tools_write_file.py — never talks to a real container.
"""

import asyncio
import base64
from dataclasses import dataclass
from types import SimpleNamespace

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


def test_write_file_has_python3_base64_fallback_chain():
    """§1.1 madde 3 (v0.4 spec): structured_tools.write_file must have the
    same command -v python3 / command -v base64 probe chain as
    tools.run_write_file, so containers without python3 (e.g.
    configure-git-webserver, see docs/plan.md) don't fail with an
    unexplained exit 127 when StructuredToolAgent is the only agent left."""
    env = FakeEnvironment(stdout="WRITE_OK\n", return_code=0)
    asyncio.run(write_file(env, "/tmp/example.txt", "hello world", timeout_sec=30))

    cmd = env.last_command
    assert "command -v python3" in cmd, "must probe for python3 before assuming it exists"
    assert "command -v base64" in cmd, "must probe for base64 before assuming it exists"
    assert "base64 -d" in cmd or "base64 --decode" in cmd, (
        "must have a base64(1)-based fallback for containers without python3"
    )
    assert "no python3 or base64 available" in cmd, (
        "must fail loudly with a clear message if neither tool exists"
    )


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


class _RealBashInMinimalPathEnvironment:
    """Actually runs the generated command via a real shell, but with PATH
    restricted so specific tools appear "not installed" — a genuine
    simulation of a minimal container (§1.1 madde 3), not just a canned
    fake response. Only `only_tool` (a directory containing exactly the
    binaries to keep, e.g. a symlink farm) is exposed via PATH; everything
    else, including python3, is invisible to `command -v`."""

    def __init__(self, path: str):
        self._path = path

    async def exec(self, command: str, timeout_sec: int):
        import subprocess

        result = subprocess.run(
            ["/bin/sh", "-c", command],
            env={"PATH": self._path},
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return SimpleNamespace(
            stdout=result.stdout, stderr=result.stderr, return_code=result.returncode
        )


def _minimal_path_with_only(tmp_path, keep: list[str]) -> str:
    """Build a directory containing symlinks only for the binaries in
    `keep` (resolved from the real PATH), so a `command -v X` inside the
    restricted PATH only succeeds for those tools."""
    import shutil

    bin_dir = tmp_path / "minimal_bin"
    bin_dir.mkdir()
    for tool in keep:
        real = shutil.which(tool)
        assert real is not None, f"test host must have {tool} installed"
        (bin_dir / tool).symlink_to(real)
    return str(bin_dir)


def test_write_file_falls_back_to_base64_when_python3_is_absent(tmp_path):
    """§1.1 madde 3: a container with base64/sh but no python3 must still
    succeed via the fallback branch, not fail with an unexplained exit 127
    (the exact regression this checklist item exists to prevent, see
    docs/plan.md's configure-git-webserver trial)."""
    path = _minimal_path_with_only(tmp_path, ["sh", "base64", "mkdir", "dirname", "printf"])
    env = _RealBashInMinimalPathEnvironment(path)
    target = tmp_path / "out" / "written.txt"

    receipt = asyncio.run(
        write_file(env, str(target), "hello from minimal env\n", timeout_sec=10)
    )

    assert receipt.exit_code == 0
    assert target.read_text() == "hello from minimal env\n"


def test_write_file_fails_loudly_when_neither_python3_nor_base64_exist(tmp_path):
    """§1.1 madde 3: with neither tool available, the command must exit
    non-zero with the explicit error message, not silently do nothing."""
    path = _minimal_path_with_only(tmp_path, ["sh", "mkdir", "dirname"])
    env = _RealBashInMinimalPathEnvironment(path)
    target = tmp_path / "out" / "written.txt"

    receipt = asyncio.run(write_file(env, str(target), "x", timeout_sec=10))

    assert receipt.exit_code == 127
    assert "no python3 or base64 available" in receipt.stderr_tail
    assert not target.exists()
