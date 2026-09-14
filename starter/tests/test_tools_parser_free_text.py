"""Regression tests for the action parser (see docs/agy-rootcause-git-apk.md
§C: regex-log/sqlite-with-gcov trials where free text outside an intended
command block, or an incidental untagged fence quoting file content, got
executed in the container as a literal shell command.

Tightened contract: only a fence explicitly tagged ```bash/```sh/```shell
is treated as an executable command. An untagged fence (often used by the
model to quote file content or show expected output, not to issue a
command) must NOT be executed.
"""

from agent.tools import parse_action


def test_untagged_fence_used_to_quote_content_is_not_executed_as_shell():
    text = (
        "Here's the current file content:\n"
        "```\n"
        "some line of file content\n"
        "another line\n"
        "```\n"
        "Now let me fix it:\n"
        "```bash\n"
        "sed -i 's/foo/bar/' file.txt\n"
        "```\n"
    )
    action = parse_action(text)
    assert action.kind == "shell"
    assert action.command == "sed -i 's/foo/bar/' file.txt"


def test_free_text_with_no_fence_at_all_is_never_executed():
    text = "But this doesn't ensure the regex is correct. Use a stricter pattern instead."
    action = parse_action(text)
    assert action.kind == "none"
    assert action.command == ""


def test_task_complete_mentioned_in_prose_is_not_false_positive_done():
    text = (
        "I still need to verify before I can say TASK_COMPLETE, so let me "
        "run the test suite first.\n"
        "```bash\npytest -q\n```"
    )
    action = parse_action(text)
    assert action.kind == "shell"
    assert action.command == "pytest -q"
