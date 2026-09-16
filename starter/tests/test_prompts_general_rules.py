"""Tests for the two general rules added in v0.4.1 (prompts.py):
(a) Output ordering rule: avoid Python `set` when order matters, use `list` or sort.
(b) Build artifact cleanup rule: clean temporary/binary (.o, etc.) build files before finishing.
Must be present in both SYSTEM_PROMPT and STRUCTURED_SYSTEM_PROMPT without syntax errors.
"""

from agent.prompts import STRUCTURED_SYSTEM_PROMPT, SYSTEM_PROMPT


def test_system_prompt_imports_and_is_non_empty():
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 0
    assert isinstance(STRUCTURED_SYSTEM_PROMPT, str)
    assert len(STRUCTURED_SYSTEM_PROMPT) > 0


def test_baseline_system_prompt_states_order_and_cleanup_rules():
    lowered = SYSTEM_PROMPT.lower()
    # Rule (a): ordering and set avoidance
    assert "set" in lowered
    assert "order" in lowered
    assert "list" in lowered or "sort" in lowered

    # Rule (b): build cleanup
    assert "clean" in lowered
    assert ".o" in lowered or "temporary" in lowered or "binary" in lowered


def test_structured_system_prompt_states_order_and_cleanup_rules():
    lowered = STRUCTURED_SYSTEM_PROMPT.lower()
    # Rule (a): ordering and set avoidance
    assert "set" in lowered
    assert "order" in lowered
    assert "list" in lowered or "sort" in lowered

    # Rule (b): build cleanup
    assert "clean" in lowered
    assert ".o" in lowered or "temporary" in lowered or "binary" in lowered


def test_prompts_rules_are_generic_not_task_specific():
    for prompt in (SYSTEM_PROMPT, STRUCTURED_SYSTEM_PROMPT):
        lowered = prompt.lower()
        for banned in ("sqlite-with-gcov", "configure-git-webserver", "log-summary-date-ranges"):
            assert banned not in lowered
