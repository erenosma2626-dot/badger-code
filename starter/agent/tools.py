"""Action parsing and command execution.

This file is the bridge between the LLM's text output and the Docker
container. It handles three things:

1. **Parsing** — Extracting a structured ``Action`` from the LLM's
   free-text response. The baseline protocol is intentionally simple so
   that even small local models (~7B) can follow it reliably:
   - A fenced ``bash`` code block → run that command in the container.
   - A fenced ``write_file:PATH`` code block → write content to PATH
     byte-exact, no shell quoting involved.
   - The literal string ``TASK_COMPLETE`` (outside any code block, or as
     the ONLY content of a code block) → stop the loop.
   - Anything else → the LLM didn't follow the protocol; agent.py will
     send a nudge message asking it to try again.

2. **Execution** — Running the parsed command inside the task's Docker
   container via Harbor's ``environment.exec()`` and formatting the
   stdout/stderr/exit-code into a string the LLM can read.

3. **Evidence-based stuck-loop detection** — comparing not just the
   command text but (command, exit_code, output_hash) triples, so a
   legitimate retry (e.g. polling a server until it's ready) isn't
   confused with genuine no-progress looping.

Output truncation
=================
Commands can produce megabytes of output (e.g., ``find /``). Feeding all of
that into the conversation would blow the model's context window. So
``run_shell()`` truncates long output to ``MAX_OBSERVATION_CHARS``, keeping
the first and last halves with a "[N characters omitted]" marker in between.
This is a blunt strategy — smarter truncation (e.g., keeping error lines,
tail-only, or summarizing) is a good improvement target.

Improvement ideas
=================
- Full native tool-calling (Nebius/OpenAI function-calling API) instead of
  markdown-fence conventions — removes ALL free-text parsing ambiguity.
  Bigger change, deliberately deferred; see docs/plan.md.
- read_file / search_text / read_output(action_id, offset) tools.
- Smarter truncation: prioritize stderr, keep the last N lines, etc.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field

from harbor.environments.base import BaseEnvironment

logger = logging.getLogger(__name__)

_bg_counter = 0

CODE_BLOCK_RE = re.compile(r"```(?:bash|sh|shell)\s*\n(.*?)```", re.DOTALL)
"""Matches a Markdown fenced code block EXPLICITLY tagged bash/sh/shell.
The captured group (1) is everything between the opening and closing
fences. Untagged fences are deliberately NOT matched here: models often
use an untagged ``` block to quote file content or expected output rather
than to issue a command, and executing that verbatim as free-text shell
input is exactly the class of bug seen in the regex-log/sqlite-with-gcov
trials (docs/agy-rootcause-git-apk.md §C) — free text like "But this
doesn't ensure..." or a stray TASK_COMPLETE got sent to the container and
failed with exit 127. Requiring an explicit tag makes that structurally
impossible."""

WRITE_FILE_RE = re.compile(r"```write_file:(\S+)\s*\n(.*?)```", re.DOTALL)
"""Matches a ```write_file:/path/to/file\\n<content>\\n``` block. Captured
groups are (1) the target path and (2) the raw file content."""

DONE_MARKER = "TASK_COMPLETE"
"""The literal string the LLM must emit (outside a code block, or as the
sole content of one) to signal that it believes the task is finished."""

MAX_OBSERVATION_CHARS = 6000
"""Maximum characters to keep from a command's combined output. Longer
output is truncated to the first and last halves with an omission notice."""

STUCK_LOOP_WINDOW = 6
"""How many recent (command, exit_code, output_hash) triples to remember
for evidence-based stuck-loop detection."""

STUCK_LOOP_THRESHOLD = 3
"""How many times the exact same (command, exit_code, output_hash) triple
must repeat within the window before it counts as a stuck loop."""


@dataclass
class Action:
    """A single action parsed from the LLM's response.

    Attributes
    ----------
    kind : str
        One of ``"shell"`` (run a command), ``"write_file"`` (write a file
        byte-exact), ``"done"`` (task complete), or ``"none"`` (no valid
        action found — LLM didn't follow protocol).
    command : str
        The bash command to execute. Only meaningful when ``kind == "shell"``.
    path : str
        Target file path. Only meaningful when ``kind == "write_file"``.
    content : str
        File content to write. Only meaningful when ``kind == "write_file"``.
    """

    kind: str
    command: str = ""
    path: str = ""
    content: str = ""


def parse_action(text: str) -> Action:
    """Extract a single action from the LLM's response text.

    Precedence: a ``write_file`` block wins over a bash block (checked
    first, distinct fence tag), a bash block wins over a bare
    ``TASK_COMPLETE`` mention — UNLESS the bash block's entire stripped
    content is exactly ``TASK_COMPLETE``, in which case it is treated as
    completion rather than executed as a literal (and doomed to fail)
    shell command. This second rule exists because smaller models
    sometimes wrap the completion marker in a code fence by mistake; see
    docs/plan.md for the polyglot-c-py trial that surfaced this bug.

    Parameters
    ----------
    text : str
        The raw text content of the LLM's response.

    Returns
    -------
    Action
        The parsed action.
    """
    write_match = WRITE_FILE_RE.search(text)
    if write_match:
        path = write_match.group(1).strip()
        content = write_match.group(2)
        if path:
            return Action("write_file", path=path, content=content)

    match = CODE_BLOCK_RE.search(text)
    if match:
        command = match.group(1).strip()
        if command == DONE_MARKER:
            return Action("done")
        if command:
            return Action("shell", command)
    if DONE_MARKER in text:
        return Action("done")
    return Action("none")


def _truncate(text: str) -> str:
    """Truncate long text, keeping the first and last halves."""
    if len(text) <= MAX_OBSERVATION_CHARS:
        return text
    half = MAX_OBSERVATION_CHARS // 2
    omitted = len(text) - MAX_OBSERVATION_CHARS
    return f"{text[:half]}\n... [{omitted} characters omitted] ...\n{text[-half:]}"


def transform_background_command(command: str) -> tuple[str, bool]:
    """If command ends with a bare '&' (not '&&'), wrap in nohup ... & disown.

    A command backgrounded this way dies the moment the shell session that
    launched it closes — which happens between agent turns. Wrapping it in
    nohup (ignore hangup signal, redirect output to a file) plus disown
    (detach from the shell's job table) keeps it alive so a later verifier
    step can actually reach it. See the configure-git-webserver trial in
    docs/plan.md for the failure this fixes.
    """
    global _bg_counter
    stripped = command.strip()
    if stripped.endswith("&") and not stripped.endswith("&&"):
        _bg_counter += 1
        log_path = f"/tmp/bg_{_bg_counter}.log"
        cmd_without_amp = stripped[:-1].rstrip()
        if "\n" in cmd_without_amp:
            lines = cmd_without_amp.split("\n")
            prefix = "\n".join(lines[:-1])
            last_cmd = lines[-1].strip()
            transformed = f"{prefix}\nnohup {last_cmd} > {log_path} 2>&1 & disown"
        else:
            transformed = f"nohup {cmd_without_amp} > {log_path} 2>&1 & disown"
        return transformed, True
    return command, False


@dataclass
class Receipt:
    """A deterministic record of one executed action.

    Unlike the raw text `ShellObservation`, every field here is a concrete
    value the model cannot misread or talk itself out of — it either ran
    successfully or it didn't, it either touched a file or it didn't.
    Motivated by Terra's (worker3) literature review: the dominant failure
    class across our regression set (regex-log, build-cython-ext,
    chess-best-move, ...) was the model believing an action succeeded
    without any evidence. See docs/plan.md.
    """

    kind: str  # "shell" or "write_file"
    command_or_path: str
    exit_code: int | None
    timed_out: bool
    declared_target_paths: list[str] = field(default_factory=list)
    content_sha256: str | None = None
    content_bytes: int | None = None

    def fingerprint(self) -> tuple:
        """A hashable key for evidence-based stuck-loop comparison."""
        return (self.kind, self.command_or_path, self.exit_code)


class ShellObservation(str):
    """String observation with a `.receipt` attribute carrying structured,
    deterministic metadata about the command that produced it (see Receipt).
    """

    receipt: Receipt

    def __new__(cls, content: str, receipt: Receipt):
        obj = super().__new__(cls, content)
        obj.receipt = receipt
        return obj


_EDIT_TARGET_RE = re.compile(
    r"(?:^|\s)(?:[0-9]|&)?>>?\s*(?!/dev/null|&)(\S+)"
)
"""Best-effort extraction of a shell redirection target (`> path` or `>>
path`), used only to populate Receipt.declared_target_paths for the edit
classifier below. Not a full shell parser — heredocs and `tee path` are
handled separately."""


def _extract_declared_targets(command: str) -> list[str]:
    """Best-effort list of file paths a shell command appears to write to."""
    targets = []
    for m in _EDIT_TARGET_RE.finditer(command):
        targets.append(m.group(1))
    tee_match = re.search(r"\btee\s+(?:-a\s+)?(\S+)", command)
    if tee_match:
        targets.append(tee_match.group(1))
    return targets


def classify_command(command: str) -> str:
    """Classify a bash command as 'edit', 'test', or 'inspect'.

    Heuristics:
    - edit: file writes (>, >>, tee , sed -i, heredoc <<EOF ... > file)
    - test: test and verification keywords (pytest, python -m pytest,
            python3 -c, python -c, ./test, make test, npm test, go test,
            curl , git clone, diff , grep -q)
    - inspect: all other commands (cat, ls, find, etc.)

    Known limitation (observed in the sqlite-with-gcov trial, see
    docs/plan.md): a command that verifies a solution by directly running
    a compiled binary (e.g. `./sqlite3 --version`) isn't in this keyword
    list and gets classified as 'inspect', producing a false-negative
    verification_status even though the task actually passed. The
    Receipt/tool-calling redesign is the real fix; this heuristic is a
    stopgap.
    """
    test_keywords = [
        "pytest",
        "python -m pytest",
        "python3 -c",
        "python -c",
        "./test",
        "make test",
        "npm test",
        "go test",
        "curl ",
        "curl\t",
        "git clone",
        "diff ",
        "diff\t",
        "grep -q",
    ]
    is_test = any(kw in command for kw in test_keywords) or command.strip() in (
        "pytest",
        "make test",
        "npm test",
        "go test",
    )

    # Exclude stream redirects (2>&1, 1>&2, >&1, >&2), /dev/null sinks, and background log sinks from edit detection
    cleaned = re.sub(r"&>|2>&1|1>&2|>&1|>&2", "", command)
    cleaned = re.sub(r"(?:[0-9]|&)?>>?\s*/dev/null", "", cleaned)
    cleaned = re.sub(r"(?:[0-9]|&)?>>?\s*/tmp/bg_\d+\.log", "", cleaned)

    is_edit = False
    if "sed -i" in command or "tee " in command or "tee\t" in command:
        is_edit = True
    elif "<<" in command and (">" in cleaned or ">>" in cleaned):
        is_edit = True
    elif ">" in cleaned or ">>" in cleaned:
        is_edit = True

    if is_edit and is_test:
        # If it has explicit file creation / sed editing, prioritize edit;
        # otherwise, e.g. pytest > test.log is primarily a test.
        if "sed -i" in command or "<<" in command:
            return "edit"
        return "test"
    if is_edit:
        return "edit"
    if is_test:
        return "test"
    return "inspect"


async def run_shell(
    environment: BaseEnvironment, command: str, timeout_sec: int
) -> ShellObservation:
    """Execute a bash command in the task's Docker container.

    Parameters
    ----------
    environment : BaseEnvironment
        Harbor's container interface. The key method is
        ``environment.exec(command=..., timeout_sec=...)``, which returns
        an ``ExecResult`` with ``.stdout``, ``.stderr``, and ``.return_code``.
    command : str
        The bash command string to run (can be multi-line).
    timeout_sec : int
        Maximum seconds to wait before killing the command.

    Returns
    -------
    ShellObservation
        A formatted string (exit code, stdout, stderr, each truncated) with
        a ``.receipt`` attribute carrying structured, deterministic metadata.
    """
    exec_command, transformed = transform_background_command(command)
    if transformed:
        logger.info(
            "Background command transformed: original=%r -> transformed=%r",
            command,
            exec_command,
        )

    try:
        result = await environment.exec(command=exec_command, timeout_sec=timeout_sec)
    except Exception as exc:
        timed_out = "timeout" in str(exc).lower() or "timed out" in str(exc).lower()
        receipt = Receipt(
            kind="shell",
            command_or_path=command,
            exit_code=None,
            timed_out=timed_out,
        )
        return ShellObservation(f"[command did not complete: {exc}]", receipt)

    parts = [f"exit code: {result.return_code}"]
    if result.stdout:
        parts.append(f"stdout:\n{_truncate(result.stdout)}")
    if result.stderr:
        parts.append(f"stderr:\n{_truncate(result.stderr)}")
    if not result.stdout and not result.stderr:
        parts.append("(no output)")
    text = "\n".join(parts)

    receipt = Receipt(
        kind="shell",
        command_or_path=command,
        exit_code=result.return_code,
        timed_out=False,
        declared_target_paths=_extract_declared_targets(command),
    )
    return ShellObservation(text, receipt)


async def run_write_file(
    environment: BaseEnvironment, path: str, content: str, timeout_sec: int
) -> ShellObservation:
    """Write `content` to `path` inside the container, byte-exact.

    Avoids all shell-quoting pitfalls (heredoc delimiters, `$`, backslashes,
    embedded quotes) by base64-encoding the content and decoding it on the
    container side via a short Python one-liner — the shell itself never
    sees or re-interprets the actual file content. Returns a receipt
    including a sha256 hash and byte count so the model has concrete proof
    the write landed correctly, rather than assuming a heredoc "worked".

    Parameters
    ----------
    environment : BaseEnvironment
        Harbor's container interface.
    path : str
        Destination path inside the container.
    content : str
        Raw file content (text). Encoded as UTF-8 before base64.
    timeout_sec : int
        Timeout for the underlying write command.
    """
    import base64

    raw = content.encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    # The destination path is base64-encoded too. `path` is LLM-controlled
    # text, not a literal — embedding it directly into a shell command
    # (e.g. via Python's `!r` repr, as this used to do) is a shell-injection
    # risk if it ever contains quotes/`$()`/backticks. Base64 output is
    # restricted to [A-Za-z0-9+/=], so neither the content nor the path can
    # break out of the surrounding quotes.
    path_b64 = base64.b64encode(path.encode("utf-8")).decode("ascii")
    sha256 = hashlib.sha256(raw).hexdigest()

    # Single environment.exec() round-trip: try python3 first (existing,
    # widely-compatible behavior), fall back to POSIX `base64 -d` (part of
    # coreutils, present in far more minimal containers than python3) if
    # python3 isn't installed, and fail loudly with a clear message if
    # neither tool exists. Doing the python3/base64 probe with `command -v`
    # inside ONE shell command (instead of probing first and writing second)
    # avoids paying for an extra exec()/turn round-trip.
    #
    # Bug this fixes: some task containers (e.g. configure-git-webserver)
    # are minimal and have no python3 at all, so every write_file call used
    # to fail with exit 127 and no explanation reached the model — see
    # jobs/2026-09-13__20-35-57/configure-git-webserver__PoxXkF8/result.json.
    write_cmd = (
        "if command -v python3 >/dev/null 2>&1; then "
        f"python3 -c \"import base64,pathlib; "
        f"p = pathlib.Path(base64.b64decode('{path_b64}').decode('utf-8')); "
        f"p.parent.mkdir(parents=True, exist_ok=True); "
        f"p.write_bytes(base64.b64decode('{b64}'))\" && echo WRITE_OK; "
        "elif command -v base64 >/dev/null 2>&1; then "
        f"__wf_path=\"$(printf '%s' '{path_b64}' | base64 -d)\" && "
        "mkdir -p \"$(dirname \"$__wf_path\")\" && "
        f"printf '%s' '{b64}' | base64 -d > \"$__wf_path\" && echo WRITE_OK; "
        "else "
        "echo 'no python3 or base64 available in container' >&2; exit 127; "
        "fi"
    )

    try:
        result = await environment.exec(command=write_cmd, timeout_sec=timeout_sec)
    except Exception as exc:
        receipt = Receipt(
            kind="write_file",
            command_or_path=path,
            exit_code=None,
            timed_out=True,
            content_sha256=sha256,
            content_bytes=len(raw),
        )
        return ShellObservation(f"[write_file did not complete: {exc}]", receipt)

    ok = result.return_code == 0 and "WRITE_OK" in (result.stdout or "")
    text = (
        f"write_file {path}: "
        + ("OK" if ok else f"FAILED (exit {result.return_code})")
        + f"\nbytes={len(raw)} sha256={sha256}"
    )
    if not ok and result.stderr:
        text += f"\nstderr:\n{_truncate(result.stderr)}"

    receipt = Receipt(
        kind="write_file",
        command_or_path=path,
        exit_code=result.return_code,
        timed_out=False,
        declared_target_paths=[path],
        content_sha256=sha256,
        content_bytes=len(raw),
    )
    return ShellObservation(text, receipt)


def output_hash(observation: str) -> str:
    """Short hash of an observation's text, used as part of the stuck-loop
    evidence fingerprint (see agent.py). Two runs of the same command with
    genuinely different output (e.g. a server that just came up) hash
    differently and are correctly treated as progress, not a stuck loop."""
    return hashlib.sha256(observation.encode("utf-8", errors="replace")).hexdigest()[:12]
