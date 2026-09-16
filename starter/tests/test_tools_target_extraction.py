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


def test_is_unproductive_attempt_build_command_exit_zero_with_not_found_is_productive():
    # Scenario (a): ./configure outputting "Checking for localtime_s...not found" with exit 0 is productive
    output = "Checking for localtime_s...not found\nconfig.status: creating Makefile"
    assert is_unproductive_attempt(0, output, command="./configure --disable-shared") is False
    assert is_unproductive_attempt(0, output, command="make -j4") is False
    assert is_unproductive_attempt(0, output, command="gcc -o main main.c") is False
    assert is_unproductive_attempt(0, output, command="python3 setup.py build") is False


def test_is_unproductive_attempt_search_command_exit_zero_with_not_found_is_unproductive():
    # Scenario (b): Search/read command with not found output is unproductive even with exit 0
    assert is_unproductive_attempt(0, "pattern not found", command="grep -rn foo src/") is True
    assert is_unproductive_attempt(0, "find: 'foo': No such file", command="find . -name foo") is True
    assert is_unproductive_attempt(0, "which: sqlite3 not found", command="which sqlite3") is True
    assert is_unproductive_attempt(0, "cat: missing.txt: not found", command="cat missing.txt") is True


def test_is_unproductive_attempt_nonzero_exit_code_always_unproductive():
    # Scenario (c): Non-zero exit code is always unproductive regardless of command
    assert is_unproductive_attempt(1, "anything", command="./configure") is True
    assert is_unproductive_attempt(127, "command not found", command="grep") is True


def test_is_unproductive_attempt_none_command_backward_compatible():
    # Scenario (d): command=None preserves existing behavior (keyword check on exit 0)
    assert is_unproductive_attempt(0, "not found", command=None) is True
    assert is_unproductive_attempt(0, "everything ok", command=None) is False

