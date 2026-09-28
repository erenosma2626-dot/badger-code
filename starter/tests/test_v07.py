"""v0.7 — token efficiency + command handling (docs/v0.7-optimizasyon-arastirma.md).

H1 history compaction, H2 per-task token budget, H3 long-running command
timeouts + apt lock wait, H4 foreground servers auto-backgrounded, H5 PID
normalization in the exact-repeat fingerprint, H6 chained-command
verification, H7 length cap 3, plus read_file windowing (the old receipt
showed only the LAST 3000 chars, so the head of a large file was never
visible — a driver of read_file loops in Faz B).
"""

import asyncio
import base64
import json
import pathlib
from dataclasses import dataclass

from agent.agent import StructuredToolAgent, is_meaningful_verification
from agent.command_policy import (
    LONG_COMMAND_TIMEOUT_SEC,
    background_foreground_server,
    command_timeout,
    fingerprint_command,
    is_foreground_server,
    prepare_command,
    timeout_hint,
)
from agent.context_budget import compact_messages
from agent.structured_tools import read_file, terminal_exec


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    return_code: int


class FakeContext:
    def __init__(self):
        self.n_input_tokens = 0
        self.n_output_tokens = 0
        self.metadata = {}


class RecordingEnv:
    def __init__(self, stdout="__AGENT_CWD_AFTER__:/app\n", rc=0):
        self.calls = []
        self._stdout = stdout
        self._rc = rc

    async def exec(self, command, timeout_sec):
        self.calls.append((command, timeout_sec))
        return FakeExecResult(self._stdout, "", self._rc)


def scripted(turns):
    class _LLM:
        def __init__(self, model_name=None):
            self.calls = 0
            self.seen = []

        async def chat_tools(self, messages, tools):
            _LLM.last_messages = messages
            idx = min(self.calls, len(turns) - 1)
            self.calls += 1
            return turns[idx]

    return _LLM


def run_agent(monkeypatch, env, turns, max_turns=10, **patches):
    import agent.agent as m

    llm = scripted(turns)
    monkeypatch.setattr(m, "LLMClient", llm)
    monkeypatch.setattr(m, "MAX_TURNS", max_turns)
    for k, v in patches.items():
        monkeypatch.setattr(m, k, v)
    ctx = FakeContext()
    asyncio.run(
        StructuredToolAgent(logs_dir=pathlib.Path("/tmp"), model_name="x").run(
            "task", env, ctx
        )
    )
    return ctx, llm


def call(i, name, **args):
    return ("", [{"id": f"c{i}", "name": name, "arguments": args}],
            {"prompt_tokens": 10, "completion_tokens": 1})


# --- H3: long-running commands ----------------------------------------------

def test_install_and_build_commands_get_long_timeout():
    for cmd in [
        "apt-get update && apt-get install -y gcc",
        "pip install numpy",
        "python3 -m pip install -r requirements.txt",
        "cd /app/sqlite && make -j4",
        "./configure --enable-gcov",
        "R -e \"install.packages('rstan')\"",
        "cargo build --release",
        "npm install",
    ]:
        assert command_timeout(cmd, 60) == LONG_COMMAND_TIMEOUT_SEC, cmd


def test_ordinary_commands_keep_default_timeout():
    for cmd in ["ls -la", "python3 solve.py", "cat Makefile", "grep make notes.txt"]:
        assert command_timeout(cmd, 60) == 60, cmd


def test_apt_commands_wait_for_dpkg_lock_and_are_noninteractive():
    out = prepare_command("apt-get install -y tcl8.6-dev")
    assert "DPkg::Lock::Timeout" in out
    assert "DEBIAN_FRONTEND=noninteractive" in out
    assert prepare_command("ls") .endswith("ls")


def test_timeout_hint_mentions_dpkg_recovery_for_apt():
    hint = timeout_hint("apt-get install -y x", 300)
    assert "dpkg --configure -a" in hint
    assert "nohup" in timeout_hint("python3 train.py", 60)


# --- H4: foreground servers ---------------------------------------------------

def test_foreground_server_patterns_detected():
    assert is_foreground_server("nginx -g 'daemon off;'")
    assert is_foreground_server("mkdir -p /run/sshd && /usr/sbin/sshd -D")
    assert is_foreground_server("python3 -m http.server 8080")
    assert not is_foreground_server("nginx -t")
    assert not is_foreground_server("python3 -m http.server 8080 &")
    assert not is_foreground_server("nohup /usr/sbin/sshd -D > /tmp/s.log 2>&1 &")


def test_foreground_server_is_rewritten_to_background():
    out = background_foreground_server("/usr/sbin/sshd -D", "/tmp/bg1.log")
    assert out.rstrip().endswith("tail -n 20 /tmp/bg1.log")
    assert "nohup" in out and "&" in out


def test_agent_backgrounds_foreground_server_and_notes_it(monkeypatch):
    env = RecordingEnv()
    ctx, _ = run_agent(monkeypatch, env, [
        call(1, "terminal_exec", command="nginx -g 'daemon off;'"),
        call(2, "task_complete", evidence="ok"),
    ])
    sent = [c for c, _ in env.calls if "daemon off" in c]
    assert sent and "nohup" in sent[0]
    tool = [m for m in ctx.metadata["messages"] if m["role"] == "tool"][0]
    assert "background" in tool["content"].lower()


def test_agent_uses_long_timeout_and_lock_wait_for_apt(monkeypatch):
    env = RecordingEnv()
    run_agent(monkeypatch, env, [
        call(1, "terminal_exec", command="apt-get install -y gcc"),
        call(2, "task_complete", evidence="ok"),
    ])
    apt = [(c, t) for c, t in env.calls if "apt-get" in c and "install" in c]
    assert apt[0][1] == LONG_COMMAND_TIMEOUT_SEC
    assert "DPkg::Lock::Timeout" in apt[0][0]


def test_timed_out_receipt_carries_hint():
    class Boom:
        async def exec(self, command, timeout_sec):
            raise TimeoutError("Command timed out after 60 seconds")

    r = asyncio.run(terminal_exec(Boom(), "apt-get install -y x", timeout_sec=60))
    assert r.timed_out
    assert "dpkg --configure -a" in (r.warning or "")


# --- H5: PID normalization ------------------------------------------------------

def test_fingerprint_normalizes_pids():
    assert fingerprint_command("kill 1107 1108 && nginx") == fingerprint_command(
        "kill 1130 1134 && nginx"
    )
    assert fingerprint_command("ls a") != fingerprint_command("ls b")


# --- H6: verification ------------------------------------------------------------

def test_chained_passive_commands_are_not_verification():
    assert not is_meaningful_verification("cd /app && ls -la")
    assert not is_meaningful_verification("grep -n foo out.txt | wc -l")
    assert not is_meaningful_verification("find /app -name '*.py'")
    assert is_meaningful_verification("cd /app && python3 -m pytest -q")
    assert is_meaningful_verification("cat in.txt | python3 check.py")


# --- read_file windowing -------------------------------------------------------

def _b64(s):
    return base64.b64encode(s.encode()).decode()


def test_read_file_large_file_shows_head_window_with_continuation():
    content = "".join(f"line {i}\n" for i in range(1, 2001))
    r = asyncio.run(read_file(RecordingEnv(stdout=_b64(content)), "/f", timeout_sec=5))
    assert r.stdout_tail.startswith("line 1\n")
    d = r.to_dict()
    assert d["total_lines"] == 2000
    assert d["next_start_line"] > 1


def test_read_file_start_line_returns_later_window():
    content = "".join(f"line {i}\n" for i in range(1, 2001))
    r = asyncio.run(
        read_file(RecordingEnv(stdout=_b64(content)), "/f", timeout_sec=5, start_line=1500)
    )
    assert r.stdout_tail.startswith("line 1500\n")


def test_read_file_binary_is_summarized_not_dumped():
    raw = bytes(range(256)) * 40
    env = RecordingEnv(stdout=base64.b64encode(raw).decode())
    r = asyncio.run(read_file(env, "/model.bin", timeout_sec=5))
    assert "binary" in (r.warning or "").lower()
    assert len(r.stdout_tail) < 400


def test_terminal_exec_long_output_keeps_head_and_tail():
    body = "HEAD-ERROR\n" + ("x" * 50 + "\n") * 400 + "TAIL-SUMMARY\n"
    r = asyncio.run(terminal_exec(RecordingEnv(stdout=body + "__AGENT_CWD_AFTER__:/app\n"), "make", timeout_sec=5))
    assert "HEAD-ERROR" in r.stdout_tail and "TAIL-SUMMARY" in r.stdout_tail
    assert len(r.stdout_tail) <= 3200


# --- H1: history compaction ----------------------------------------------------

def _hist(n_tools):
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "TASK"}]
    for i in range(n_tools):
        msgs.append({"role": "assistant", "content": "thinking " * 200, "tool_calls": [
            {"id": f"t{i}", "type": "function", "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": f"/a{i}.py", "content": "y" * 5000})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"t{i}",
                     "content": json.dumps({"tool": "write_file", "exit_code": 0,
                                            "stdout_tail": "z" * 3000})})
    return msgs


def test_compaction_keeps_recent_full_and_shrinks_old():
    msgs = _hist(10)
    out = compact_messages(msgs, keep_recent=3)
    assert len(out) == len(msgs)
    assert out[0] == msgs[0] and out[1] == msgs[1]
    assert out[-1] == msgs[-1] and out[-2] == msgs[-2]
    assert len(json.dumps(out)) < len(json.dumps(msgs)) * 0.5
    old_tool = out[3]
    assert old_tool["tool_call_id"] == "t0"
    assert json.loads(old_tool["content"])["exit_code"] == 0
    old_args = json.loads(out[2]["tool_calls"][0]["function"]["arguments"])
    assert old_args["path"] == "/a0.py" and len(old_args["content"]) < 300
    assert msgs[3]["content"].count("z") == 3000  # original untouched


def test_agent_sends_compacted_history_but_records_full(monkeypatch):
    env = RecordingEnv(stdout="q" * 3000 + "\n__AGENT_CWD_AFTER__:/app\n")
    turns = [call(i, "terminal_exec", command=f"echo {i}") for i in range(12)]
    ctx, llm = run_agent(monkeypatch, env, turns, max_turns=12, KEEP_RECENT_TOOL_RESULTS=3)
    sent = json.dumps(llm.last_messages)
    full = json.dumps(ctx.metadata["messages"])
    assert len(sent) < len(full) * 0.6


# --- H2: token budget ------------------------------------------------------------

def _big(i):
    return ("", [{"id": f"b{i}", "name": "terminal_exec", "arguments": {"command": f"echo {i}"}}],
            {"prompt_tokens": 40_000, "completion_tokens": 100})


def test_budget_warning_then_termination(monkeypatch):
    ctx, _ = run_agent(monkeypatch, RecordingEnv(), [_big(i) for i in range(20)],
                       max_turns=20, TOKEN_BUDGET=200_000)
    assert ctx.metadata["termination_reason"] == "token_budget_exhausted"
    assert ctx.n_input_tokens + ctx.n_output_tokens <= 200_000 + 40_100
    warnings = [m for m in ctx.metadata["messages"]
                if m["role"] == "user" and "budget" in m["content"].lower()]
    assert len(warnings) == 1


# --- H7: length cap -------------------------------------------------------------

def test_three_consecutive_length_truncations_terminate(monkeypatch):
    L = {"prompt_tokens": 1, "completion_tokens": 1, "finish_reason": "length"}
    ctx, _ = run_agent(monkeypatch, RecordingEnv(), [(f"b{i}", [], L) for i in range(9)])
    assert ctx.metadata["termination_reason"] == "consecutive_length_truncation"
    assert ctx.metadata["turns"] == 3
