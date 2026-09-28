"""Command handling policy for terminal_exec (v0.7, H3/H4/H5).

Faz B evidence (docs/v0.7-optimizasyon-arastirma.md):

- H3: 121 commands hit the 60s timeout, 53 of them apt. Killing apt-get
  mid-install left the dpkg lock held in 20 tasks, and the model then
  burned turns in kill/`dpkg --configure -a` loops (sqlite-with-gcov,
  configure-git-webserver, build-pmars...). Install/build commands get a
  longer timeout, apt waits for the lock instead of failing on it, and a
  timed-out receipt carries a concrete recovery hint.
- H4: servers started in the foreground (`nginx -g 'daemon off;'`,
  `sshd -D`) never return, so every call cost a full timeout; nginx was
  retried ~25 times with only the PIDs changing. Such commands are run in
  the background with their log tailed.
- H5: the exact-repeat stuck-loop fingerprint compared raw command text,
  so `kill 1107 && ...` vs `kill 1130 && ...` never matched. Numbers are
  normalized in the fingerprint only (never in the executed command).
"""

from __future__ import annotations

import os
import re

LONG_COMMAND_TIMEOUT_SEC = int(os.environ.get("AGENT_LONG_COMMAND_TIMEOUT_SEC", "300"))

_LONG_RUNNING_RE = re.compile(
    r"""(?x)
    \b(apt-get|apt|aptitude)\s+(-\S+\s+)*(install|update|upgrade|dist-upgrade|build-dep)\b
    | \bpip3?\s+install\b | \b-m\s+pip\s+install\b | \buv\s+(pip\s+install|sync)\b
    | \bconda\s+(install|create|env)\b | \bmamba\s+install\b
    | \bnpm\s+(install|ci)\b | \byarn(\s+install)?\s*($|&&|;) | \bpnpm\s+install\b
    | \bcargo\s+(build|install|test)\b | \bgo\s+(build|install|mod\s+download)\b
    | (^|[\s;&|(])make(\s|$) | \bcmake\s+--build\b | \bninja\b
    | (^|[\s;&|(])\./configure\b | \bmvn\s | \bgradle\s | \bgem\s+install\b
    | install\.packages\( | \bopam\s+install\b | \bstack\s+build\b
    """
)

_APT_RE = re.compile(r"\b(apt-get|apt)\s+(?=(-\S+\s+)*(install|update|upgrade|dist-upgrade|build-dep|remove)\b)")

_FOREGROUND_RE = re.compile(
    r"""(?x)
    daemon\s+off
    | \bsshd\b[^;&|]*\s-D\b
    | \b-m\s+http\.server\b
    | \b(uvicorn|gunicorn|hypercorn)\s+\S
    | \bflask\s+run\b
    | \bredis-server\b(?![^;&|]*--daemonize\s+yes)
    | \bmongod\b(?![^;&|]*--fork)
    | \bnpm\s+(start|run\s+(dev|serve|start))\b
    | \bhttpd\b[^;&|]*-DFOREGROUND
    """
)

_DAEMONIZED_RE = re.compile(r"(&\s*$)|\bnohup\b|\bsetsid\b|\bdisown\b|\bdaemonize\b|\btmux\b|\bscreen\s+-d")


def command_timeout(command: str, default: int) -> int:
    """Timeout for ``command``: long for install/build steps, else default."""
    if _LONG_RUNNING_RE.search(command):
        return max(default, LONG_COMMAND_TIMEOUT_SEC)
    return default


def prepare_command(command: str) -> str:
    """Make apt non-interactive and wait for the dpkg lock instead of
    failing on it. Other commands pass through unchanged."""
    if not _APT_RE.search(command):
        return command
    patched = _APT_RE.sub(lambda m: f"{m.group(1)} -o DPkg::Lock::Timeout=120 ", command)
    return f"export DEBIAN_FRONTEND=noninteractive; {patched}"


def is_foreground_server(command: str) -> bool:
    stripped = command.strip()
    if _DAEMONIZED_RE.search(stripped):
        return False
    return bool(_FOREGROUND_RE.search(stripped))


def background_foreground_server(command: str, log_path: str) -> str:
    """Run ``command`` detached, give it a moment, show its log."""
    quoted = command.replace("'", "'\"'\"'")
    return (
        f"nohup bash -c '{quoted}' > {log_path} 2>&1 &\n"
        f"sleep 3; echo \"[backgrounded pid $!] log: {log_path}\"; "
        f"tail -n 20 {log_path}"
    )


def fingerprint_command(command: str) -> str:
    """Command text for loop detection: multi-digit numbers (PIDs, ports
    that change per attempt) collapsed so near-identical retries match."""
    return re.sub(r"\b\d{2,}\b", "N", command.strip())


def timeout_hint(command: str, timeout_sec: int) -> str:
    hint = (
        f"The command was killed after {timeout_sec}s. Do not rerun it the same way. "
        "For long jobs, run them in the background: "
        "`nohup <cmd> > /tmp/job.log 2>&1 &` then check `tail /tmp/job.log` in later turns. "
        "Servers must be started in the background, never in the foreground."
    )
    if _APT_RE.search(command) or "dpkg" in command:
        hint += (
            " A killed apt/dpkg can leave the package lock held: run "
            "`dpkg --configure -a` once, then retry the install once "
            "(do not kill processes by PID in a loop)."
        )
    return hint
