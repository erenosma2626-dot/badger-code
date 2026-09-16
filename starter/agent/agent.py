"""The main agent loop — this is where Harbor calls into your code.

How it works
============
Harbor orchestrates Terminal-Bench tasks. For each task it:
  1. Spins up a fresh Docker container with the task's source code and tests.
  2. Calls **your agent's** ``setup()`` (install tools if needed) and then
     ``run()`` (solve the task).
  3. After ``run()`` returns (or times out), Harbor runs the task's test suite
     against the container's final state to produce a reward (1.0 = pass).

This file implements ``BaselineAgent``, a ReAct
(https://arxiv.org/abs/2210.03629) loop with guardrails added after
studying 8 real trial transcripts (see docs/plan.md for the full analysis):

    ┌────────────────────────────────────────────────────┐
    │  Send conversation (system prompt + history) to the │
    │  LLM via HTTP (see llm.py)                          │
    │                                                     │
    │  Parse the LLM's response (see tools.py):           │
    │    ```bash ...```          → run in container       │
    │    ```write_file:PATH...```→ write byte-exact       │
    │    TASK_COMPLETE            → check for evidence,   │
    │                                then stop the loop    │
    │    anything else           → nudge the LLM to act    │
    │                                                     │
    │  Append a deterministic Receipt (not raw text guess) │
    │  back as context. Repeat up to MAX_TURNS.            │
    └────────────────────────────────────────────────────┘

The agent **never touches your host filesystem** — it can only run commands
inside the task's Docker container via ``environment.exec()``.

Guardrails in this version
===========================
- **Environment bootstrap**: before turn 1, a fixed `pwd && ls -la` runs
  automatically and its output is prepended to the task instruction, so the
  model can't answer a task (chess-best-move trial) without at least seeing
  what's in front of it.
- **Evidence-based stuck-loop detection**: flags a loop only when the same
  command AND the same exit code AND the same output repeat 3x — not just
  the same command text. A legitimate retry (e.g. polling a server until
  it's up) produces different output each time and is never flagged.
- **Persistent background services**: a bare trailing `&` is rewritten to
  `nohup ... & disown` so services survive past their own shell session.
- **write_file tool**: writes bytes directly (via base64, no shell requoting)
  and returns a sha256 + byte count receipt, avoiding the heredoc-quoting
  corruption class of bugs.
- **Completion-evidence check**: if TASK_COMPLETE is declared with no
  successful test/verification since the last edit, the model gets ONE
  nudge asking what evidence supports that — not a hard block.

What's still NOT here (deliberately deferred, see docs/plan.md)
=================================================================
- Full native tool-calling (Nebius function-calling API) — would remove
  regex-based parsing entirely but is a bigger, riskier redesign that
  deserves its own dedicated testing pass.
- A generic "package/tool missing and no network" recovery strategy.
- Forcing the model to `cat` a file before grepping it (still prompt-level,
  not mechanically enforced).

Run it
======
::

    harbor run -d terminal-bench@2.0 \\
        --agent agent.agent:BaselineAgent \\
        -i fix-git

Environment variables
=====================
- ``AGENT_MAX_TURNS``  — max reasoning/action cycles per task (default: 100).
- ``AGENT_COMMAND_TIMEOUT_SEC`` — per-command timeout in seconds (default: 60).
- ``AGENT_STUCK_LOOP_WINDOW`` — how many recent actions to compare (default: 6).
"""

from collections import deque
import json
import os

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from agent.llm import LLMClient
from agent.prompts import (
    COMPLETION_EVIDENCE_MESSAGE,
    NUDGE_MESSAGE,
    STRUCTURED_COMPLETION_EVIDENCE_MESSAGE,
    STRUCTURED_NUDGE_MESSAGE,
    STRUCTURED_SYSTEM_PROMPT,
    STUCK_LOOP_MESSAGE,
    SYSTEM_PROMPT,
    TARGET_STUCK_LOOP_MESSAGE,
    observation_message,
)
from agent.structured_tools import TOOL_SCHEMAS
from agent.structured_tools import read_file as structured_read_file
from agent.structured_tools import terminal_exec as structured_terminal_exec
from agent.structured_tools import write_file as structured_write_file
from agent.tools import (
    classify_command,
    extract_target,
    is_unproductive_attempt,
    output_hash,
    parse_action,
    run_shell,
    run_write_file,
)

MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "100"))
COMMAND_TIMEOUT_SEC = int(os.environ.get("AGENT_COMMAND_TIMEOUT_SEC", "60"))
STUCK_LOOP_WINDOW = int(os.environ.get("AGENT_STUCK_LOOP_WINDOW", "6"))
STUCK_LOOP_THRESHOLD = 3

BOOTSTRAP_COMMAND = (
    "pwd && echo --- && ls -la && echo --- && ls -la /app 2>/dev/null "
    "&& echo --- && find /app -type f 2>/dev/null | head -200 "
    "&& echo --- && cat /etc/os-release 2>/dev/null | grep PRETTY_NAME "
    "&& echo --- && command -v apt-get apk git python3"
)
"""Run once, before turn 1, so the model sees the actual working directory
and file layout before it does anything else. Motivated by the
chess-best-move trial (docs/plan.md), where the agent wrote a hardcoded
answer without ever looking at the task's input files. Also surfaces the
OS identity and available package manager/tools up front, so the model
never has to guess it (see docs/agy-rootcause-git-apk.md: the agent
assumed an Alpine container and tried `apk` when the real container was
Ubuntu with `apt-get` available all along).

§2.2 (v0.4 spec): the top-level `ls -la /app` alone wasn't enough — the
log-summary/Structured trial (docs/plan.md) only read the 3 files it
happened to notice in a shallow listing and never discovered the rest of
`/app/logs`. The `find /app -type f` line gives a FULL recursive listing
of every file in the task directory up front, so the model can't miss
input it never thought to look for (capped at 200 paths so a huge task
tree doesn't blow the first message's token budget)."""


class BaselineAgent(BaseAgent):
    """A ReAct agent that solves tasks by issuing bash commands or writing
    files directly, with evidence-based guardrails against the failure
    modes observed in this project's own trial logs (docs/plan.md).

    Harbor discovers this class via the ``--agent`` CLI flag.
    It calls ``setup()`` once, then ``run()`` once per task. The class must
    implement all four methods below (``name``, ``version``, ``setup``,
    ``run``) — that's the Harbor BaseAgent contract.
    """

    @staticmethod
    def name() -> str:
        return "mlm26-baseline"

    def version(self) -> str | None:
        return "0.2.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        """Called once before ``run()``. Install tools inside the container.

        The baseline needs nothing, but if your agent relies on tools like
        ripgrep, jq, or a custom script inside the container, install them
        here via ``environment.exec(command="apt-get install -y ...")``.

        Note: finale tasks may have **no network access** inside the
        container, so anything you install here must not require downloads.
        """
        pass

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Solve the task. This is the main agent loop.

        Parameters
        ----------
        instruction : str
            The task description. This is what the LLM sees as the first
            user message (with an environment-bootstrap snapshot prepended).
        environment : BaseEnvironment
            The Docker container interface. The only way to interact with the
            task is ``environment.exec(command=..., timeout_sec=...)``, which
            returns an ``ExecResult`` with ``.stdout``, ``.stderr``, and
            ``.return_code``.
        context : AgentContext
            A mutable object where you report token usage and metadata.
            Harbor reads this after ``run()`` returns (or times out) to
            record stats in ``result.json``. **Update it every turn** so
            that even a timeout produces partial usage data.
        """
        llm = LLMClient(model_name=self.model_name)

        # Environment bootstrap: show the model what it's actually working
        # with before it takes a single action. This doesn't cost a turn —
        # it's folded into the first user message.
        bootstrap_observation = await run_shell(
            environment, BOOTSTRAP_COMMAND, timeout_sec=COMMAND_TIMEOUT_SEC
        )
        augmented_instruction = (
            f"{instruction}\n\n"
            f"Automatic environment snapshot (pwd, current directory listing, "
            f"and /app if present) — inspect it before acting:\n"
            f"{bootstrap_observation}"
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": augmented_instruction},
        ]

        n_input = 0
        n_output = 0
        turns = 0
        finished = False
        termination_reason: str | None = None

        # Evidence-based stuck-loop state: compare (kind, command_or_path,
        # exit_code, output_hash) fingerprints, not raw command text. A
        # retried command whose *outcome* changes (e.g. polling a server
        # until it's ready) is never mistaken for a stuck loop.
        recent_fingerprints: deque[tuple] = deque(maxlen=STUCK_LOOP_WINDOW)
        stuck_nudged = False

        # §2.3 (v0.4 spec) — same-target stuck-loop: N unproductive
        # attempts against the SAME extracted target (file/path), even if
        # the command text differs each time (a varying grep pattern
        # against the same file that never reads it directly, etc.).
        target_attempt_counts: dict[str, int] = {}

        has_edited = False
        pending_verification = False
        had_successful_test_after_edit = False
        completion_evidence_nudged = False
        # §2.1 (v0.4 spec, tightened) — whether any genuine tool-call
        # (write_file or a shell command, regardless of outcome) has
        # happened since the completion-evidence nudge was sent. A second
        # TASK_COMPLETE that arrives with this still False means the model
        # just re-declared done from text alone — rejected hard, not
        # nudged a third time (see the done-branch below).
        action_since_nudge = False

        def compute_verification_status() -> str:
            if not has_edited:
                return "not_applicable"
            if not pending_verification:
                return "passed"
            if had_successful_test_after_edit:
                return "stale"
            return "missing"

        for _ in range(MAX_TURNS):
            turns += 1

            # 1. Ask the LLM what to do next.
            text, usage = await llm.chat(messages)
            n_input += usage.get("prompt_tokens", 0)
            n_output += usage.get("completion_tokens", 0)

            # Update context every turn (not just at the end) so that if
            # Harbor kills us for a timeout, partial stats are still saved.
            context.n_input_tokens = n_input
            context.n_output_tokens = n_output
            context.metadata = {
                "turns": turns,
                "finished": finished,
                "messages": messages,
                "termination_reason": termination_reason,
                "verification_status": compute_verification_status(),
            }

            messages.append({"role": "assistant", "content": text})

            # 2. Parse the response into an action (see tools.py).
            action = parse_action(text)

            if action.kind == "done":
                if pending_verification and not completion_evidence_nudged:
                    # One gentle check before accepting completion: has
                    # anything actually verified the last edit? See the
                    # regex-log / log-summary-date-ranges / polyglot-c-py
                    # trials in docs/plan.md — all three declared done with
                    # zero evidence.
                    completion_evidence_nudged = True
                    action_since_nudge = False
                    messages.append(
                        {"role": "user", "content": COMPLETION_EVIDENCE_MESSAGE}
                    )
                    continue

                if pending_verification and not action_since_nudge:
                    # §2.1 (tightened, v0.4 spec) — the log-summary-date-ranges
                    # trial (docs/plan.md) showed the old one-nudge-then-
                    # always-accept gate doesn't catch a "yüzeysel öz-doğrulama":
                    # the model responding to the nudge with narrative alone
                    # and re-declaring done, no new tool-call/receipt in
                    # between. That is rejected HARD here — not nudged a
                    # third time (no infinite-loop risk: this is a terminal
                    # decision, not another retry).
                    self.logger.warning(
                        "turn %d: TASK_COMPLETE re-declared with no new "
                        "tool-call since the completion-evidence nudge; "
                        "rejecting hard",
                        turns,
                    )
                    termination_reason = "completion_rejected_no_new_evidence"
                    context.metadata["termination_reason"] = termination_reason
                    context.metadata[
                        "verification_status"
                    ] = compute_verification_status()
                    break

                finished = True
                termination_reason = "task_complete"
                context.metadata["finished"] = True
                context.metadata["termination_reason"] = termination_reason
                context.metadata["verification_status"] = compute_verification_status()
                break

            if action.kind == "none":
                # The LLM didn't produce a valid action. Nudge it to follow
                # the protocol.
                messages.append({"role": "user", "content": NUDGE_MESSAGE})
                continue

            if action.kind == "write_file":
                observation = await run_write_file(
                    environment,
                    action.path,
                    action.content,
                    timeout_sec=COMMAND_TIMEOUT_SEC,
                )
                has_edited = True
                pending_verification = True
                completion_evidence_nudged = False
                action_since_nudge = True

                fingerprint = observation.receipt.fingerprint()
                recent_fingerprints.append(fingerprint)
                messages.append(
                    {"role": "user", "content": observation_message(observation)}
                )
                continue

            # action.kind == "shell" from here on.

            # 3. Execute the command, THEN check whether its outcome is a
            # genuine repeat (evidence-based, not just matching command text).
            self.logger.info("turn %d: %s", turns, action.command[:200])
            observation = await run_shell(
                environment, action.command, timeout_sec=COMMAND_TIMEOUT_SEC
            )
            action_since_nudge = True

            fingerprint = (
                *observation.receipt.fingerprint(),
                output_hash(str(observation)),
            )
            repeat_count = sum(1 for f in recent_fingerprints if f == fingerprint)
            recent_fingerprints.append(fingerprint)

            # §2.3 — same-target detection: track unproductive attempts
            # (non-zero exit or a "didn't find it" signal) against the same
            # extracted target, independent of whether the command text
            # itself repeats verbatim.
            target = extract_target(action.command)
            target_is_stuck = False
            if target:
                if is_unproductive_attempt(
                    observation.receipt.exit_code,
                    str(observation),
                    command=action.command,
                ):
                    target_attempt_counts[target] = (
                        target_attempt_counts.get(target, 0) + 1
                    )
                else:
                    target_attempt_counts[target] = 0
                target_is_stuck = (
                    target_attempt_counts[target] >= STUCK_LOOP_THRESHOLD
                )

            exact_repeat_stuck = repeat_count + 1 >= STUCK_LOOP_THRESHOLD

            if exact_repeat_stuck or target_is_stuck:
                if not stuck_nudged:
                    stuck_nudged = True
                    if exact_repeat_stuck:
                        self.logger.warning(
                            "turn %d: stuck loop detected (same command, "
                            "exit code, and output %d times), sending nudge",
                            turns,
                            repeat_count + 1,
                        )
                        nudge_content = STUCK_LOOP_MESSAGE
                    else:
                        self.logger.warning(
                            "turn %d: stuck loop detected (%d unproductive "
                            "attempts against target %r), sending nudge",
                            turns,
                            target_attempt_counts[target],
                            target,
                        )
                        nudge_content = TARGET_STUCK_LOOP_MESSAGE.format(target=target)
                    messages.append({"role": "user", "content": nudge_content})
                    continue
                else:
                    self.logger.warning(
                        "turn %d: stuck loop repeated after nudge, terminating",
                        turns,
                    )
                    termination_reason = "stuck_loop_detected"
                    context.metadata["termination_reason"] = termination_reason
                    context.metadata[
                        "verification_status"
                    ] = compute_verification_status()
                    break

            # Track verification status based on command classification and
            # exit code (a heuristic — see classify_command's docstring for
            # its known false-negative on binary-execution-as-verification).
            cmd_type = classify_command(action.command)
            exit_code = observation.receipt.exit_code

            if cmd_type == "edit":
                has_edited = True
                pending_verification = True
                completion_evidence_nudged = False
            elif cmd_type == "test":
                if exit_code == 0 and has_edited:
                    pending_verification = False
                    had_successful_test_after_edit = True

            # 4. Feed the output back to the LLM as context for the next turn.
            messages.append(
                {"role": "user", "content": observation_message(observation)}
            )

        if termination_reason is None:
            termination_reason = "max_turns"
        context.metadata["termination_reason"] = termination_reason
        context.metadata["verification_status"] = compute_verification_status()


class StructuredToolAgent(BaseAgent):
    """A ReAct agent using native tool-calling (terminal_exec, write_file,
    read_file, task_complete — see agent/structured_tools.py) instead of
    markdown-fence text parsing. This is the "next target architecture"
    from docs/plan.md's second mermaid diagram: it structurally eliminates
    the "TASK_COMPLETE / free text sent as a literal command" bug class
    (tools.py's CODE_BLOCK_RE fix mitigates it for the text-based agent;
    this removes the failure mode entirely by having the API itself parse
    the model's intent, not a regex).

    Requires an LLM endpoint that supports OpenAI-style function-calling
    (Nebius does). Falls back to nudging, same as BaselineAgent, if the
    model responds with no tool call.
    """

    @staticmethod
    def name() -> str:
        return "mlm26-structured-tools"

    def version(self) -> str | None:
        return "0.3.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        pass

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        llm = LLMClient(model_name=self.model_name)

        bootstrap_observation = await run_shell(
            environment, BOOTSTRAP_COMMAND, timeout_sec=COMMAND_TIMEOUT_SEC
        )
        augmented_instruction = (
            f"{instruction}\n\n"
            f"Automatic environment snapshot (pwd, current directory listing, "
            f"OS, and available tools) — inspect it before acting:\n"
            f"{bootstrap_observation}"
        )

        messages = [
            {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
            {"role": "user", "content": augmented_instruction},
        ]

        n_input = 0
        n_output = 0
        turns = 0
        finished = False
        termination_reason: str | None = None

        # verification_status tracking (v0.4 spec §1.1 madde 1), derived
        # from the receipt stream rather than BaselineAgent's shell-command
        # classifier: write_file is unambiguously the only "edit" tool here,
        # and any terminal_exec with exit_code=0 counts as verification
        # (StructuredToolAgent has no separate edit/test/inspect split for
        # shell commands the way tools.classify_command does for
        # BaselineAgent's free-text bash blocks).
        has_edited = False
        pending_verification = False
        had_successful_test_after_edit = False

        def compute_verification_status() -> str:
            if not has_edited:
                return "not_applicable"
            if not pending_verification:
                return "passed"
            if had_successful_test_after_edit:
                return "stale"
            return "missing"

        # §1.1 madde 2 / §2.3 (v0.4 spec) — evidence-based stuck-loop
        # detection, ported from BaselineAgent and applied to
        # terminal_exec/read_file (write_file's success/failure is already
        # covered by verification_status above). Two triggers, either one
        # nudges once then hard-terminates on repeat, same as BaselineAgent:
        # (a) exact repeat — same tool+command/path+exit_code+output_hash;
        # (b) same-target — N unproductive attempts against the same
        # extracted file/path even if the command text varies each turn.
        recent_fingerprints: deque[tuple] = deque(maxlen=STUCK_LOOP_WINDOW)
        target_attempt_counts: dict[str, int] = {}
        stuck_nudged = False

        # §2.1 (tightened, v0.4 spec) — same completion-evidence gate as
        # BaselineAgent: one nudge on the first task_complete while
        # pending_verification, then a second task_complete is accepted
        # ONLY if a genuine new tool call happened since the nudge; a bare
        # re-declare is rejected hard (terminal decision, no third nudge).
        completion_evidence_nudged = False
        action_since_nudge = False

        for _ in range(MAX_TURNS):
            turns += 1

            text, tool_calls, usage = await llm.chat_tools(messages, TOOL_SCHEMAS)
            n_input += usage.get("prompt_tokens", 0)
            n_output += usage.get("completion_tokens", 0)

            context.n_input_tokens = n_input
            context.n_output_tokens = n_output
            context.metadata = {
                "turns": turns,
                "finished": finished,
                "messages": messages,
                "termination_reason": termination_reason,
                "verification_status": compute_verification_status(),
            }

            # Native tool-calling assistant messages must carry the raw
            # tool_calls structure (id/name/arguments) for the API to
            # accept the following tool-role reply, not just plain text.
            assistant_msg: dict = {"role": "assistant", "content": text}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                    for call in tool_calls
                ]
            messages.append(assistant_msg)

            if not tool_calls:
                # Observability for the tool-call parser mismatch (see
                # docs/v0.4-diagnosis-toolcall.md): before this, a rejected
                # response only produced "you didn't call a tool" — the raw
                # content the model actually sent was never surfaced
                # anywhere, so a persistent parser/format mismatch (e.g. a
                # max_tokens-truncated tool-call payload) was indistinguishable
                # from the model simply narrating. Log it in full every time.
                self.logger.warning(
                    "turn %d: model response had no recognized tool_calls "
                    "(finish_reason=%s); raw content: %r",
                    turns,
                    usage.get("finish_reason"),
                    text,
                )
                messages.append(
                    {"role": "user", "content": STRUCTURED_NUDGE_MESSAGE}
                )
                continue

            # Exactly one tool call per turn by prompt contract; if the
            # model sends more, only the first is executed and the rest
            # are acknowledged as skipped so the tool-call/tool-reply
            # pairing the API requires stays intact.
            call = tool_calls[0]
            name = call["name"]
            args = call["arguments"]

            if name == "task_complete":
                if pending_verification and not completion_evidence_nudged:
                    # §2.1 — one nudge before accepting completion; see
                    # BaselineAgent's identical gate for the trials this
                    # addresses (docs/plan.md).
                    completion_evidence_nudged = True
                    action_since_nudge = False
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(
                                {"acknowledged": False, "reason": "insufficient evidence"}
                            ),
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": STRUCTURED_COMPLETION_EVIDENCE_MESSAGE,
                        }
                    )
                    continue

                if pending_verification and not action_since_nudge:
                    # §2.1 (tightened) — a second task_complete with no new
                    # tool call since the nudge is rejected HARD, not
                    # nudged a third time (no infinite-loop risk).
                    self.logger.warning(
                        "turn %d: task_complete re-declared with no new "
                        "tool call since the completion-evidence nudge; "
                        "rejecting hard",
                        turns,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(
                                {"acknowledged": False, "reason": "insufficient evidence"}
                            ),
                        }
                    )
                    termination_reason = "completion_rejected_no_new_evidence"
                    context.metadata["termination_reason"] = termination_reason
                    context.metadata[
                        "verification_status"
                    ] = compute_verification_status()
                    break

                finished = True
                termination_reason = "task_complete"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(
                            {"acknowledged": True, "evidence": args.get("evidence", "")}
                        ),
                    }
                )
                context.metadata["finished"] = True
                context.metadata["termination_reason"] = termination_reason
                context.metadata["verification_status"] = compute_verification_status()
                break

            if name == "terminal_exec":
                receipt = await structured_terminal_exec(
                    environment, args.get("command", ""), timeout_sec=COMMAND_TIMEOUT_SEC
                )
                action_since_nudge = True
                if has_edited and receipt.exit_code == 0:
                    pending_verification = False
                    had_successful_test_after_edit = True
            elif name == "write_file":
                receipt = await structured_write_file(
                    environment,
                    args.get("path", ""),
                    args.get("content", ""),
                    timeout_sec=COMMAND_TIMEOUT_SEC,
                )
                has_edited = True
                pending_verification = True
                completion_evidence_nudged = False
                action_since_nudge = True
            elif name == "read_file":
                receipt = await structured_read_file(
                    environment, args.get("path", ""), timeout_sec=COMMAND_TIMEOUT_SEC
                )
                action_since_nudge = True
            else:
                receipt_dict = {"error": f"unknown tool: {name}"}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(receipt_dict),
                    }
                )
                for extra in tool_calls[1:]:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": extra["id"],
                            "content": json.dumps({"skipped": True}),
                        }
                    )
                continue

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(receipt.to_dict()),
                }
            )
            for extra in tool_calls[1:]:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": extra["id"],
                        "content": json.dumps({"skipped": True}),
                    }
                )

            if name in ("terminal_exec", "read_file"):
                command_or_path = (
                    args.get("command", "") if name == "terminal_exec"
                    else args.get("path", "")
                )
                combined_output = receipt.stdout_tail + receipt.stderr_tail
                fingerprint = (
                    name,
                    command_or_path,
                    receipt.exit_code,
                    output_hash(combined_output),
                )
                repeat_count = sum(1 for f in recent_fingerprints if f == fingerprint)
                recent_fingerprints.append(fingerprint)

                target = (
                    command_or_path if name == "read_file"
                    else extract_target(command_or_path)
                )
                target_is_stuck = False
                if target:
                    cmd = None if name == "read_file" else command_or_path
                    if is_unproductive_attempt(
                        receipt.exit_code, combined_output, command=cmd
                    ):
                        target_attempt_counts[target] = (
                            target_attempt_counts.get(target, 0) + 1
                        )
                    else:
                        target_attempt_counts[target] = 0
                    target_is_stuck = (
                        target_attempt_counts[target] >= STUCK_LOOP_THRESHOLD
                    )

                exact_repeat_stuck = repeat_count + 1 >= STUCK_LOOP_THRESHOLD

                if exact_repeat_stuck or target_is_stuck:
                    if not stuck_nudged:
                        stuck_nudged = True
                        if exact_repeat_stuck:
                            self.logger.warning(
                                "turn %d: stuck loop detected (same %s, "
                                "exit code, and output %d times), sending "
                                "nudge",
                                turns,
                                name,
                                repeat_count + 1,
                            )
                            nudge_content = STUCK_LOOP_MESSAGE
                        else:
                            self.logger.warning(
                                "turn %d: stuck loop detected (%d "
                                "unproductive attempts against target %r), "
                                "sending nudge",
                                turns,
                                target_attempt_counts[target],
                                target,
                            )
                            nudge_content = TARGET_STUCK_LOOP_MESSAGE.format(
                                target=target
                            )
                        messages.append({"role": "user", "content": nudge_content})
                    else:
                        self.logger.warning(
                            "turn %d: stuck loop repeated after nudge, "
                            "terminating",
                            turns,
                        )
                        termination_reason = "stuck_loop_detected"
                        context.metadata["termination_reason"] = termination_reason
                        context.metadata[
                            "verification_status"
                        ] = compute_verification_status()
                        break

        if termination_reason is None:
            termination_reason = "max_turns"
        context.metadata["termination_reason"] = termination_reason
        context.metadata["verification_status"] = compute_verification_status()
