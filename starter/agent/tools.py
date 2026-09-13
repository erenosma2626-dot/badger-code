"""Action parsing and command execution.

This file is the bridge between the LLM's text output and the Docker
container. It handles two things:

1. **Parsing** — Extracting a structured ``Action`` from the LLM's
   free-text response. The baseline protocol is intentionally simple so
   that even small local models (~7B) can follow it reliably:
   - A fenced ``bash`` code block → run that command in the container.
   - The literal string ``TASK_COMPLETE`` → stop the loop.
   - Anything else → the LLM didn't follow the protocol; agent.py will
     send a nudge message asking it to try again.

2. **Execution** — Running the parsed command inside the task's Docker
   container via Harbor's ``environment.exec()`` and formatting the
   stdout/stderr/exit-code into a string the LLM can read.

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
- Add richer action types (read_file, write_file, search) so the LLM
  doesn't have to compose raw bash for common operations.
- Parse multiple code blocks and execute them sequentially.
- Detect and break out of repeated-command loops.
- Smarter truncation: prioritize stderr, keep the last N lines, etc.
"""

import logging
import re
from dataclasses import dataclass

from harbor.environments.base import BaseEnvironment

logger = logging.getLogger(__name__)

_bg_counter = 0

CODE_BLOCK_RE = re.compile(r"```(?:bash|sh|shell)?\s*\n(.*?)```", re.DOTALL)
"""Matches a Markdown fenced code block tagged as bash/sh/shell (or untagged).
The captured group (1) is everything between the opening and closing fences."""

DONE_MARKER = "TASK_COMPLETE"
"""The literal string the LLM must emit (outside a code block) to signal
that it believes the task is finished."""

MAX_OBSERVATION_CHARS = 6000
"""Maximum characters to keep from a command's combined output. Longer
output is truncated to the first and last halves with an omission notice."""


@dataclass
class Action:
    """A single action parsed from the LLM's response.

    Attributes
    ----------
    kind : str
        One of ``"shell"`` (run a command), ``"done"`` (task complete),
        or ``"none"`` (no valid action found — LLM didn't follow protocol).
    command : str
        The bash command to execute. Only meaningful when ``kind == "shell"``.
    """

    kind: str
    command: str = ""


def parse_action(text: str) -> Action:
    """Extract a single action from the LLM's response text.

    Precedence: a code block wins over a ``TASK_COMPLETE`` mention, so the
    model can discuss finishing without accidentally terminating.

    Parameters
    ----------
    text : str
        The raw text content of the LLM's response.

    Returns
    -------
    Action
        The parsed action. ``kind`` is ``"shell"`` if a bash block was found,
        ``"done"`` if TASK_COMPLETE was found (and no code block), or
        ``"none"`` if neither was present.
    """
    match = CODE_BLOCK_RE.search(text)
    if match:
        command = match.group(1).strip()
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
    """If command ends with a bare '&' (not '&&'), wrap in nohup ... & disown."""
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


class ShellObservation(str):
    """String observation with an exit_code attribute."""

    exit_code: int | None

    def __new__(cls, content: str, exit_code: int | None = None):
        obj = super().__new__(cls, content)
        obj.exit_code = exit_code
        return obj


def classify_command(command: str) -> str:
    """Classify a bash command as 'edit', 'test', or 'inspect'.

    Heuristics:
    - edit: file writes (>, >>, tee , sed -i, heredoc <<EOF ... > file)
    - test: test and verification keywords (pytest, python -m pytest,
            python3 -c, python -c, ./test, make test, npm test, go test,
            curl , git clone, diff , grep -q)
    - inspect: all other commands (cat, ls, find, etc.)
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
        A formatted string containing the exit code, stdout, and stderr
        (each truncated to ``MAX_OBSERVATION_CHARS``) with an ``.exit_code``
        attribute. This string is what gets fed back to the LLM as the command's "observation."
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
        return ShellObservation(f"[command did not complete: {exc}]", exit_code=None)

    parts = [f"exit code: {result.return_code}"]
    if result.stdout:
        parts.append(f"stdout:\n{_truncate(result.stdout)}")
    if result.stderr:
        parts.append(f"stderr:\n{_truncate(result.stderr)}")
    if not result.stdout and not result.stderr:
        parts.append("(no output)")
    return ShellObservation("\n".join(parts), exit_code=result.return_code)
