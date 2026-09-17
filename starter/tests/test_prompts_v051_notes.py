"""Tests for the v0.5.1 prompt notes (prompts.py):
1. PATH / environment variable persistence note:
   - `export PATH=...` / environment variables do not persist across separate commands or to external verification processes.
   - Recommend permanent mechanisms (e.g., symlink to /usr/local/bin, /usr/bin, or shell profiles).
2. Batch processing note:
   - When processing multiple (e.g. 5+) similar files (e.g. logs), do not read them one by one.
   - Write a single script (with loops/globbing) to process all files in batch.
Must be present in both SYSTEM_PROMPT and STRUCTURED_SYSTEM_PROMPT as general rules, without task-specific hardcoding.
"""

from agent.prompts import STRUCTURED_SYSTEM_PROMPT, SYSTEM_PROMPT


def test_baseline_system_prompt_states_path_persistence_rule():
    lowered = SYSTEM_PROMPT.lower()
    assert "export path" in lowered or "export" in lowered
    assert "persist" in lowered
    assert "/usr/local/bin" in lowered or "symlink" in lowered
    assert "verifier" in lowered or "verification" in lowered


def test_structured_system_prompt_states_path_persistence_rule():
    lowered = STRUCTURED_SYSTEM_PROMPT.lower()
    assert "export path" in lowered or "export" in lowered
    assert "persist" in lowered
    assert "/usr/local/bin" in lowered or "symlink" in lowered
    assert "verifier" in lowered or "verification" in lowered


def test_baseline_system_prompt_states_batch_processing_rule():
    lowered = SYSTEM_PROMPT.lower()
    assert "one by one" in lowered
    assert "script" in lowered
    assert "batch" in lowered or "loop" in lowered or "glob" in lowered


def test_structured_system_prompt_states_batch_processing_rule():
    lowered = STRUCTURED_SYSTEM_PROMPT.lower()
    assert "one by one" in lowered
    assert "script" in lowered
    assert "batch" in lowered or "loop" in lowered or "glob" in lowered


def test_prompts_remain_generic_and_avoid_task_names():
    for prompt in (SYSTEM_PROMPT, STRUCTURED_SYSTEM_PROMPT):
        lowered = prompt.lower()
        for banned in (
            "sqlite-with-gcov",
            "log-summary-date-ranges",
            "chess-best-move",
            "fix-code-vulnerability",
        ):
            assert banned not in lowered
