"""§2.2 (v0.4 spec) — a general (not task-specific) rule that a `cd` in one
turn does not persist to the next, since each command runs in a fresh
shell invocation. Motivated by the sqlite-with-gcov and build-cython-ext
trials (docs/plan.md): the model repeatedly re-learned this the hard way
across turns instead of being told up front. Must be present in BOTH
system prompts (BaselineAgent and StructuredToolAgent)."""

from agent.prompts import STRUCTURED_SYSTEM_PROMPT, SYSTEM_PROMPT


def test_baseline_system_prompt_states_cd_is_not_persistent():
    assert "cd" in SYSTEM_PROMPT
    assert "not persist" in SYSTEM_PROMPT or "isn't persistent" in SYSTEM_PROMPT
    assert "cd X && Y" in SYSTEM_PROMPT or "&&" in SYSTEM_PROMPT
    assert "absolute path" in SYSTEM_PROMPT


def test_structured_system_prompt_states_cd_is_not_persistent():
    assert "cd" in STRUCTURED_SYSTEM_PROMPT
    assert (
        "not persist" in STRUCTURED_SYSTEM_PROMPT
        or "isn't persistent" in STRUCTURED_SYSTEM_PROMPT
    )
    assert "absolute path" in STRUCTURED_SYSTEM_PROMPT
