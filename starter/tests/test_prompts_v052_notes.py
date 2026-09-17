"""Tests for v0.5.2 prompt updates (prompts.py):
Fix 2: Guidance against pathological regexes / negative lookaheads, recommending
       plain Python processing (line-by-line, basic string/date parsing).
Fix 3: Guidance on active python3 interpreter vs system package managers (apt-get),
       recommending python3 -m pip install for the active environment.
Must be present in both SYSTEM_PROMPT and STRUCTURED_SYSTEM_PROMPT as general rules,
without task-specific hardcoding.
"""

from agent.prompts import STRUCTURED_SYSTEM_PROMPT, SYSTEM_PROMPT


def test_baseline_system_prompt_advises_against_pathological_regex_and_suggests_plain_python():
    lowered = SYSTEM_PROMPT.lower()
    assert "finish_reason=length" in lowered or "token limit" in lowered
    assert "negative lookahead" in lowered
    assert "line-by-line" in lowered or "line by line" in lowered
    assert "python" in lowered


def test_structured_system_prompt_advises_against_pathological_regex_and_suggests_plain_python():
    lowered = STRUCTURED_SYSTEM_PROMPT.lower()
    assert "finish_reason=length" in lowered or "token limit" in lowered
    assert "negative lookahead" in lowered
    assert "line-by-line" in lowered or "line by line" in lowered
    assert "python" in lowered


def test_prompts_remain_generic_and_avoid_task_names():
    for prompt in (SYSTEM_PROMPT, STRUCTURED_SYSTEM_PROMPT):
        lowered = prompt.lower()
        for banned in (
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
