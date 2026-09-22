"""Tests for v0.5.3 prompt updates (prompts.py):
Guidance on splitting large files across multiple write_file calls using append=true
to avoid finish_reason=length truncation and lost tool calls.
Must be present in both SYSTEM_PROMPT and STRUCTURED_SYSTEM_PROMPT as general rules,
without task-specific hardcoding.
"""

from agent.prompts import STRUCTURED_SYSTEM_PROMPT, SYSTEM_PROMPT


def test_baseline_system_prompt_advises_on_chunked_write_and_append():
    lowered = SYSTEM_PROMPT.lower()
    assert "write_file" in lowered
    assert "finish_reason=length" in lowered or "token limit" in lowered
    assert "append=true" in lowered or "append=True".lower() in lowered
    assert "append=false" in lowered or "append=False".lower() in lowered
    assert "chunk" in lowered or "piece" in lowered or "parça" in lowered


def test_structured_system_prompt_advises_on_chunked_write_and_append():
    lowered = STRUCTURED_SYSTEM_PROMPT.lower()
    assert "write_file" in lowered
    assert "finish_reason=length" in lowered or "token limit" in lowered
    assert "append=true" in lowered or "append=True".lower() in lowered
    assert "append=false" in lowered or "append=False".lower() in lowered
    assert "chunk" in lowered or "piece" in lowered or "parça" in lowered


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
