"""Tests for v0.6 prompt updates (prompts.py):
Item 4: Guidance on installing source-compiled Python packages into the active environment
        using `pip install .` (or `pip install -e .`) rather than leaving them at `build_ext --inplace`.
"""

from agent.prompts import STRUCTURED_SYSTEM_PROMPT, SYSTEM_PROMPT


def test_baseline_system_prompt_advises_on_source_build_install():
    lowered = SYSTEM_PROMPT.lower()
    assert "build_ext" in lowered
    assert "inplace" in lowered or "in-place" in lowered
    assert "pip install ." in lowered or "pip install -e ." in lowered


def test_structured_system_prompt_advises_on_source_build_install():
    lowered = STRUCTURED_SYSTEM_PROMPT.lower()
    assert "build_ext" in lowered
    assert "inplace" in lowered or "in-place" in lowered
    assert "pip install ." in lowered or "pip install -e ." in lowered


def test_baseline_system_prompt_advises_on_service_management_and_hosts():
    lowered = SYSTEM_PROMPT.lower()
    assert "systemd" in lowered or "systemctl" in lowered
    assert "service" in lowered or "daemon" in lowered
    assert "/etc/hosts" in lowered
    assert "append" in lowered
    assert "overwrite" in lowered


def test_structured_system_prompt_advises_on_service_management_and_hosts():
    lowered = STRUCTURED_SYSTEM_PROMPT.lower()
    assert "systemd" in lowered or "systemctl" in lowered
    assert "service" in lowered or "daemon" in lowered
    assert "/etc/hosts" in lowered
    assert "append" in lowered
    assert "overwrite" in lowered


def test_prompts_remain_generic_and_avoid_task_names():
    for prompt in (SYSTEM_PROMPT, STRUCTURED_SYSTEM_PROMPT):
        lowered = prompt.lower()
        for banned in (
            "pyknotid",
            "regex-log",
            "build-cython-ext",
            "polyglot-c-py",
            "sqlite-with-gcov",
            "log-summary-date-ranges",
            "chess-best-move",
            "fix-code-vulnerability",
            "configure-git-webserver",
        ):
            assert banned not in lowered
