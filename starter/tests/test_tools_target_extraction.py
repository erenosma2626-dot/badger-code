"""Tests for the "same target, N unproductive attempts" stuck-loop signal
(v0.4 spec §2.3): extract_target() and is_unproductive_attempt() are the
building blocks shared by BaselineAgent and StructuredToolAgent.
"""

from agent.tools import extract_target, is_unproductive_attempt


def test_extract_target_finds_trailing_path_in_grep_command():
    assert extract_target("grep -rn 'def foo' src/utils/helpers.py") == "src/utils/helpers.py"


def test_extract_target_finds_path_with_extension_and_no_slash():
    assert extract_target("cat config.yaml") == "config.yaml"


def test_extract_target_returns_none_for_command_with_no_path_like_token():
    assert extract_target("pwd") is None
    assert extract_target("ls -la") is None


def test_extract_target_from_read_file_path_argument_directly():
    assert extract_target("/app/src/main.c") == "/app/src/main.c"


def test_is_unproductive_attempt_true_on_nonzero_exit_code():
    assert is_unproductive_attempt(1, "") is True
    assert is_unproductive_attempt(127, "some output") is True


def test_is_unproductive_attempt_false_on_zero_exit_with_useful_output():
    assert is_unproductive_attempt(0, "def foo():\n    pass\n") is False


def test_is_unproductive_attempt_true_on_not_found_keyword_even_with_exit_zero():
    assert is_unproductive_attempt(0, "cat: config.yaml: No such file or directory") is True
    assert is_unproductive_attempt(None, "grep: pattern not found") is True
