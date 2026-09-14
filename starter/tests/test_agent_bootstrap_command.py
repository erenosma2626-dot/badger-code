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
