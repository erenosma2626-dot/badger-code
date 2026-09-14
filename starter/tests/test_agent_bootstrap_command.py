"""The first-turn bootstrap snapshot (agent.py's BOOTSTRAP_COMMAND) must
also surface the OS identity and available package managers/tools, so the
model never has to guess (see docs/agy-rootcause-git-apk.md: the agent
assumed Alpine and tried `apk` when the container was actually Ubuntu with
apt-get available)."""

from agent.agent import BOOTSTRAP_COMMAND


def test_bootstrap_includes_os_release_check():
    assert "/etc/os-release" in BOOTSTRAP_COMMAND
    assert "PRETTY_NAME" in BOOTSTRAP_COMMAND


def test_bootstrap_includes_package_manager_and_tool_probe():
    assert "command -v apt-get apk git python3" in BOOTSTRAP_COMMAND


def test_bootstrap_includes_full_recursive_task_directory_listing():
    """§2.2 (v0.4 spec) — the log-summary/Structured trial (docs/plan.md)
    only ever saw the top-level `ls -la /app` and never discovered most of
    the task's actual input files. The bootstrap must surface a FULL
    (recursive) file listing of the task directory, not just the top
    level, so the model can't miss files it never thought to list."""
    assert "find /app" in BOOTSTRAP_COMMAND
    assert "-type f" in BOOTSTRAP_COMMAND
