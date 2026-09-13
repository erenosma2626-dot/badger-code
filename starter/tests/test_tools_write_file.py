"""Tests for run_write_file()'s python3/base64 fallback.

Bug context: `run_write_file()` used to shell out to a bare `python3 -c ...`
one-liner to write files byte-exact inside the task container. Some task
containers (observed: configure-git-webserver, v0.2.0 trial
jobs/2026-09-13__20-35-57/configure-git-webserver__PoxXkF8/result.json) are
minimal and do NOT have python3 installed, so every write_file call failed
with exit code 127 and no actionable explanation reached the model.

These tests exercise the *command string* that gets sent to
`environment.exec()`, using a fake environment that just records the
command instead of talking to a real Docker container.
"""

import asyncio
import base64
import hashlib
from dataclasses import dataclass

import pytest

from agent.tools import run_write_file


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    return_code: int


class FakeEnvironment:
    """Records the exact command it was asked to run and returns a
    canned result. Never touches a real container."""

    def __init__(self, stdout: str = "WRITE_OK\n", stderr: str = "", return_code: int = 0):
        self.last_command: str | None = None
        self.last_timeout: int | None = None
        self._stdout = stdout
        self._stderr = stderr
        self._return_code = return_code

    async def exec(self, command: str, timeout_sec: int) -> FakeExecResult:
        self.last_command = command
        self.last_timeout = timeout_sec
        return FakeExecResult(self._stdout, self._stderr, self._return_code)


def test_write_cmd_tries_python3_first_and_falls_back_to_base64():
    """The single command sent to exec() must check for python3 AND
    fall back to a base64-based shell path in the SAME command (one
    exec() round-trip, no extra turn/latency cost)."""
    env = FakeEnvironment()
    asyncio.run(run_write_file(env, "/tmp/example.txt", "hello world", timeout_sec=30))

    assert env.last_command is not None
    cmd = env.last_command
    assert "python3" in cmd, "python3 path must still be attempted first (backward compat)"
    assert "command -v python3" in cmd, "must probe for python3 before assuming it exists"
    assert "base64 -d" in cmd or "base64 --decode" in cmd, (
        "must have a base64(1)-based fallback for containers without python3"
    )
    assert "command -v base64" in cmd, "must probe for base64 before assuming it exists"


def test_write_cmd_reports_error_when_neither_available_is_encoded_in_shell():
    """We can't easily simulate 'neither tool exists' without a real
    container, but the generated command must contain an explicit
    else-branch producing a clear error rather than silently doing
    nothing."""
    env = FakeEnvironment()
    asyncio.run(run_write_file(env, "/tmp/example.txt", "hello world", timeout_sec=30))
    cmd = env.last_command
    assert "no python3 or base64 available" in cmd


def test_write_cmd_does_not_embed_raw_path_with_special_shell_chars():
    """Regression guard against shell injection: a path containing a
    single quote (fully attacker/model controlled) must never appear
    verbatim inside the generated shell command. It should be
    base64-encoded and decoded on the container side instead."""
    env = FakeEnvironment()
    dangerous_path = "/tmp/it's a $(dangerous) 'path'.txt"
    asyncio.run(run_write_file(env, dangerous_path, "content", timeout_sec=30))

    cmd = env.last_command
    assert dangerous_path not in cmd, "raw path must not be interpolated into the shell command"
    # The path must instead be recoverable from a base64 blob embedded in the command.
    found = False
    for token in cmd.replace("\n", " ").split():
        token = token.strip("'\";()$")
        try:
            decoded = base64.b64decode(token + "=" * (-len(token) % 4), validate=False)
            if decoded == dangerous_path.encode("utf-8"):
                found = True
                break
        except Exception:
            continue
    assert found, "expected the path to be recoverable as a base64-encoded token in the command"


def test_run_write_file_returns_correct_sha256_and_bytes_on_success():
    env = FakeEnvironment(stdout="WRITE_OK\n", return_code=0)
    content = "byte-exact café content \n"
    obs = asyncio.run(run_write_file(env, "/tmp/f.txt", content, timeout_sec=30))

    raw = content.encode("utf-8")
    assert obs.receipt.content_sha256 == hashlib.sha256(raw).hexdigest()
    assert obs.receipt.content_bytes == len(raw)
    assert obs.receipt.exit_code == 0
    assert "OK" in str(obs)


def test_run_write_file_reports_failure_on_nonzero_exit():
    env = FakeEnvironment(stdout="", stderr="boom", return_code=1)
    obs = asyncio.run(run_write_file(env, "/tmp/f.txt", "x", timeout_sec=30))
    assert obs.receipt.exit_code == 1
    assert "FAILED" in str(obs)
