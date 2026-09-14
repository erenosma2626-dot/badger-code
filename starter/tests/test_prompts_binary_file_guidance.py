"""General guidance for binary/media files (RULES.md §4: no task-specific
hardcoding allowed, so this must be phrased generically, not naming any
specific task or file). Motivated by the chess-best-move trial where the
agent tried `identify`/`hexdump` (absent from a minimal container) instead
of falling back to Python's stdlib/PIL to inspect the file."""

from agent.prompts import SYSTEM_PROMPT


def test_prompt_mentions_binary_media_file_fallback():
    lowered = SYSTEM_PROMPT.lower()
    assert ".png" in lowered or "binary" in lowered or "media" in lowered
    assert "pil" in lowered or "struct" in lowered
    assert "python" in lowered


def test_prompt_guidance_is_generic_not_task_specific():
    # RULES.md §4: no per-task hardcoding in the shared system prompt.
    lowered = SYSTEM_PROMPT.lower()
    for banned in ("chess", "chess_board.png", "sqlite-with-gcov", "regex-log"):
        assert banned not in lowered
