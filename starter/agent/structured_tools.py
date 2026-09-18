"""Structured, native tool-calling primitives for the coding agent.

This is the "next target architecture" from docs/plan.md's second mermaid
diagram: instead of the model emitting free-text that a regex parser
(tools.py) has to guess the intent of, the model calls one of four
explicit, JSON-schema-typed tools via the LLM API's native function-calling
support (Nebius/OpenAI-compatible ``tools=`` parameter):

- ``terminal_exec``  — run a shell command in the container.
- ``write_file``     — write a file byte-exact.
- ``read_file``       — read a file's content directly (no shell quoting).
- ``task_complete``  — declare the task finished, with required evidence.

Every tool call returns a deterministic :class:`ExecutionReceipt` (not a
raw text blob the model has to interpret): exit_code, timeout, cwd_after,
truncated stdout/stderr, a best-effort list of changed paths, and an
output_ref the model can quote in future turns. This structurally
eliminates the "TASK_COMPLETE embedded in a code fence gets executed as a
literal command" bug class (see tools.py's CODE_BLOCK_RE fix) because
``task_complete`` is never text the model has to format correctly — it is
a distinct tool the API itself parses out of free text.

This module is deliberately independent of tools.py's markdown-fence
parser: it doesn't replace BaselineAgent (kept for models/endpoints
without function-calling support), it powers a new, parallel
``StructuredToolAgent`` in agent.py.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from dataclasses import dataclass, field

from harbor.environments.base import BaseEnvironment

MAX_TAIL_CHARS = 3000
"""Max characters kept for stdout_tail/stderr_tail in a receipt."""

_output_store: dict[str, str] = {}
"""In-memory store of full (untruncated) command output, keyed by
output_ref, so the model can be told "the full output is at ref X" without
paying its full token cost in every receipt. Cleared per agent run by the
caller if desired; not persisted across processes."""


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "terminal_exec",
            "description": (
                "Run a bash command inside the task container and get back "
                "a deterministic execution receipt (exit code, cwd after, "
                "stdout/stderr tail, changed paths)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to run. Non-interactive only.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file inside the container, byte-exact "
                "(no shell quoting involved). Creates parent directories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Destination path."},
                    "content": {
                        "type": "string",
                        "description": "Exact file content to write.",
                    },
                    "append": {
                        "type": "boolean",
                        "description": (
                            "If true, append content to the end of the file "
                            "instead of overwriting. Default is false (overwrite)."
                        ),
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's content directly from the container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to read."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": (
                "Declare the task fully finished. Must include concrete "
                "evidence (e.g. which test/command proved it works)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "evidence": {
                        "type": "string",
                        "description": (
                            "What concrete evidence shows the task is done "
                            "(a test that passed, a command whose real "
                            "output matches what's expected)."
                        ),
                    },
                },
                "required": ["evidence"],
            },
        },
    },
]


@dataclass
class ExecutionReceipt:
    """A deterministic record of one structured tool call.

    Every field here is a concrete value, not something the model has to
    infer from prose — the point of the native-tool-calling redesign.
    """

    tool: str
    exit_code: int | None = None
    timed_out: bool = False
    cwd_after: str | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    changed_paths: list[str] = field(default_factory=list)
    output_ref: str | None = None
    content_sha256: str | None = None
    content_bytes: int | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "cwd_after": self.cwd_after,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "changed_paths": self.changed_paths,
            "output_ref": self.output_ref,
            "content_sha256": self.content_sha256,
            "content_bytes": self.content_bytes,
            "error": self.error,
        }


def _tail(text: str, limit: int = MAX_TAIL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _store_output(full_text: str) -> str:
    ref = uuid.uuid4().hex[:12]
    _output_store[ref] = full_text
    return ref


def get_stored_output(ref: str) -> str | None:
    """Look up the full (untruncated) output for an output_ref."""
    return _output_store.get(ref)


# A sentinel marker used to split the command's real output from the
# cwd-probe we append to every terminal_exec call, so cwd_after is always
# a concrete fact rather than an assumption carried over from the model's
# last known directory.
_CWD_MARKER = "__AGENT_CWD_AFTER__"


async def terminal_exec(
    environment: BaseEnvironment, command: str, timeout_sec: int
) -> ExecutionReceipt:
    """Run `command`, returning a deterministic ExecutionReceipt.

    Appends a `pwd` probe after the command (same shell invocation) so
    cwd_after is a fact, not an assumption — a `cd` inside `command`
    changes what the model should believe its next command runs in.
    changed_paths is a best-effort list derived from `find <cwd> -newer
    <marker> -mmin -1` around the call; it can miss changes outside the
    working directory or under heavy concurrent I/O, which is an accepted
    limitation of a single round-trip design (see module improvement notes
    in agent.py for the full-fidelity alternative).
    """
    marker = f"/tmp/.agent_marker_{uuid.uuid4().hex[:8]}"
    wrapped = (
        f"touch {marker} 2>/dev/null; "
        f"{command}\n"
        f"__ec=$?; echo {_CWD_MARKER}:$(pwd); "
        f"find . -newer {marker} -type f 2>/dev/null | head -50; "
        f"rm -f {marker} 2>/dev/null; exit $__ec"
    )
    try:
        result = await environment.exec(command=wrapped, timeout_sec=timeout_sec)
    except Exception as exc:
        timed_out = "timeout" in str(exc).lower() or "timed out" in str(exc).lower()
        return ExecutionReceipt(
            tool="terminal_exec", exit_code=None, timed_out=timed_out, error=str(exc)
        )

    stdout = result.stdout or ""
    cwd_after = None
    changed_paths: list[str] = []
    if _CWD_MARKER in stdout:
        before, _, after_marker = stdout.partition(_CWD_MARKER + ":")
        rest_lines = after_marker.split("\n")
        cwd_after = rest_lines[0].strip() if rest_lines else None
        changed_paths = [line.strip() for line in rest_lines[1:] if line.strip()]
        stdout = before
    ref = _store_output(stdout + (("\n" + result.stderr) if result.stderr else ""))

    return ExecutionReceipt(
        tool="terminal_exec",
        exit_code=result.return_code,
        timed_out=False,
        cwd_after=cwd_after,
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(result.stderr or ""),
        changed_paths=changed_paths,
        output_ref=ref,
    )


async def write_file(
    environment: BaseEnvironment,
    path: str,
    content: str,
    timeout_sec: int,
    append: bool = False,
) -> ExecutionReceipt:
    """Write `content` to `path` byte-exact, base64-encoded end to end so
    neither path nor content can break shell quoting (same approach as
    tools.run_write_file, kept independent so this module has no
    dependency on the free-text parser it's meant to replace).

    If `append` is True, appends content to the existing file (or creates it
    if absent). If False (default), overwrites existing content.
    """
    is_append = append is True or str(append).lower() in ("true", "1")
    raw = content.encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    path_b64 = base64.b64encode(path.encode("utf-8")).decode("ascii")
    sha256 = hashlib.sha256(raw).hexdigest()

    py_write = (
        f"open(p, 'ab').write(base64.b64decode('{b64}'))"
        if is_append
        else f"p.write_bytes(base64.b64decode('{b64}'))"
    )
    sh_redirect = ">>" if is_append else ">"

    write_cmd = (
        "if command -v python3 >/dev/null 2>&1; then "
        f"python3 -c \"import base64,pathlib; "
        f"p = pathlib.Path(base64.b64decode('{path_b64}').decode('utf-8')); "
        f"p.parent.mkdir(parents=True, exist_ok=True); "
        f"{py_write}\" && echo WRITE_OK; "
        "elif command -v base64 >/dev/null 2>&1; then "
        f"__wf_path=\"$(printf '%s' '{path_b64}' | base64 -d)\" && "
        "mkdir -p \"$(dirname \"$__wf_path\")\" && "
        f"printf '%s' '{b64}' | base64 -d {sh_redirect} \"$__wf_path\" && echo WRITE_OK; "
        "else "
        "echo 'no python3 or base64 available in container' >&2; exit 127; "
        "fi"
    )
    try:
        result = await environment.exec(command=write_cmd, timeout_sec=timeout_sec)
    except Exception as exc:
        return ExecutionReceipt(
            tool="write_file",
            exit_code=None,
            timed_out=True,
            error=str(exc),
            content_sha256=sha256,
            content_bytes=len(raw),
        )

    ok = result.return_code == 0 and "WRITE_OK" in (result.stdout or "")
    return ExecutionReceipt(
        tool="write_file",
        exit_code=result.return_code,
        timed_out=False,
        changed_paths=[path] if ok else [],
        stderr_tail=_tail(result.stderr or "") if not ok else "",
        content_sha256=sha256,
        content_bytes=len(raw),
    )


async def read_file(
    environment: BaseEnvironment, path: str, timeout_sec: int
) -> ExecutionReceipt:
    """Read `path`'s content directly, base64-encoded round trip so the
    receipt's output_ref carries byte-exact content regardless of binary
    content or shell-unsafe characters."""
    path_b64 = base64.b64encode(path.encode("utf-8")).decode("ascii")
    read_cmd = (
        "if command -v python3 >/dev/null 2>&1; then "
        f"python3 -c \""
        f"import base64,pathlib,sys; "
        f"p = pathlib.Path(base64.b64decode('{path_b64}').decode('utf-8')); "
        f"p.exists() or (sys.stderr.write(f'No such file: {{p}}\\n'), sys.exit(1)); "
        f"p.is_dir() and (sys.stderr.write(f'Is a directory: {{p}}\\n'), sys.exit(1)); "
        f"sys.stdout.write(base64.b64encode(p.read_bytes()).decode('ascii'))\"; "
        "elif command -v base64 >/dev/null 2>&1; then "
        f"__rf_path=\"$(printf '%s' '{path_b64}' | base64 -d 2>/dev/null || printf '%s' '{path_b64}' | base64 -D 2>/dev/null)\"; "
        "if [ ! -e \"$__rf_path\" ]; then "
        "echo \"No such file: $__rf_path\" >&2; exit 1; "
        "elif [ -d \"$__rf_path\" ]; then "
        "echo \"Is a directory: $__rf_path\" >&2; exit 1; "
        "fi; "
        "base64 < \"$__rf_path\" | tr -d '\\n'; "
        "else "
        "echo 'no python3 or base64 available in container' >&2; exit 127; "
        "fi"
    )
    try:
        result = await environment.exec(command=read_cmd, timeout_sec=timeout_sec)
    except Exception as exc:
        return ExecutionReceipt(
            tool="read_file", exit_code=None, timed_out=True, error=str(exc)
        )

    if result.return_code != 0:
        err_msg = (result.stderr or "").strip() or (result.stdout or "").strip()
        return ExecutionReceipt(
            tool="read_file",
            exit_code=result.return_code,
            stderr_tail=_tail(err_msg),
            error=err_msg or f"read_file failed with exit code {result.return_code}",
        )

    stdout_text = (result.stdout or "").strip()
    try:
        raw = base64.b64decode(stdout_text)
        text = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        err_text = (result.stderr or "").strip() or stdout_text
        combined = f"{stdout_text} {result.stderr or ''}".lower()
        if "no such file" in combined or "not found" in combined:
            msg = f"No such file: {path}"
        elif "is a directory" in combined:
            msg = f"Is a directory: {path}"
        else:
            msg = f"No such file: {path}" if not stdout_text else f"decode failed: {exc}"
        return ExecutionReceipt(
            tool="read_file",
            exit_code=1 if result.return_code == 0 else result.return_code,
            error=msg,
            stderr_tail=_tail(err_text),
        )

    ref = _store_output(text)
    return ExecutionReceipt(
        tool="read_file",
        exit_code=0,
        stdout_tail=_tail(text),
        output_ref=ref,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        content_bytes=len(raw),
    )
