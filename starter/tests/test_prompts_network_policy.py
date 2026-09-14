"""Regression test for the git/apk root-cause (docs/agy-rootcause-git-apk.md):
the old SYSTEM_PROMPT told the model "there is no network... do NOT
apt-get install", which is false for many task containers and caused the
model to hallucinate an Alpine environment and abandon the task instead of
running `apt-get install` when apt-get was right there in /usr/bin.

The revised prompt must:
- never assert network access is universally absent,
- tell the model to check the OS and package manager first,
- tell the model to use apt-get/apk appropriately if available,
- explicitly forbid giving up and declaring the environment broken.
"""

from agent.prompts import SYSTEM_PROMPT


def test_prompt_does_not_assert_no_network_absolutely():
    lowered = SYSTEM_PROMPT.lower()
    assert "there is no network" not in lowered
    assert "do not attempt to install it over the network" not in lowered


def test_prompt_instructs_checking_os_and_package_manager_first():
    assert "/etc/os-release" in SYSTEM_PROMPT
    assert "command -v apt-get apk" in SYSTEM_PROMPT or (
        "apt-get" in SYSTEM_PROMPT and "apk" in SYSTEM_PROMPT
    )


def test_prompt_forbids_abandoning_task_as_broken_environment():
    lowered = SYSTEM_PROMPT.lower()
    assert "do not" in lowered and "abandon" in lowered or "give up" in lowered
