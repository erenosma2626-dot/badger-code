"""Tests for find_cyclic_multi_target_loop() (v0.4.1 madde 1): detects an
agent cycling between N>=2 distinct targets (A->B->C->D->A->B->C->D->...)
without ever making progress on any single one — a failure mode neither
exact_repeat_stuck (same command repeated) nor target_is_stuck (N
consecutive unproductive attempts against ONE target) can catch, since no
single target is ever revisited consecutively. Observed in
fix-code-vulnerability (J9UYqAB, VbHnBir) and build-cython-ext (hw5bn2L,
A7UN4fj) trials: 9-10 files cycled through for 100 turns, write_file never
called.
"""

from agent.tools import find_cyclic_multi_target_loop


def test_two_full_cycles_through_four_targets_is_detected():
    history = ["a.py", "b.py", "c.py", "d.py", "a.py", "b.py", "c.py", "d.py"]
    cycle = find_cyclic_multi_target_loop(history)
    assert cycle == ["a.py", "b.py", "c.py", "d.py"]


def test_one_and_a_half_cycles_is_not_detected():
    history = ["a.py", "b.py", "c.py", "d.py", "a.py", "b.py"]
    assert find_cyclic_multi_target_loop(history) is None


def test_two_full_cycles_through_two_targets_is_detected():
    history = ["a.py", "b.py", "a.py", "b.py"]
    assert find_cyclic_multi_target_loop(history) == ["a.py", "b.py"]


def test_same_single_target_repeated_is_not_flagged_as_cyclic():
    """A single target repeated isn't a *multi*-target cycle — that's
    target_is_stuck's job, not this function's."""
    history = ["a.py", "a.py", "a.py", "a.py"]
    assert find_cyclic_multi_target_loop(history) is None


def test_short_history_is_not_flagged():
    assert find_cyclic_multi_target_loop(["a.py", "b.py"]) is None
    assert find_cyclic_multi_target_loop([]) is None


def test_non_cyclic_history_is_not_flagged():
    history = ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py", "h.py"]
    assert find_cyclic_multi_target_loop(history) is None


def test_two_full_cycles_through_ten_targets_is_detected():
    """9-10 distinct targets cycled through for 2 full laps (20 entries).
    With default max_window=8 this was missed; with calibrated max_window=44
    it is detected."""
    targets = [f"file{i}.py" for i in range(10)]
    history = targets * 2
    assert find_cyclic_multi_target_loop(history) == targets


def test_two_full_cycles_through_ten_targets_with_read_and_exec_is_detected():
    """Real-world fix-code-vulnerability scenario: 10 distinct files, each visited
    twice per lap (read_file + terminal_exec cat) = 20 entries per lap, 40 entries
    total across 2 full laps. With default max_window=44 this is detected."""
    lap = [item for i in range(10) for item in (f"file{i}.py", f"file{i}.py")]
    history = lap * 2
    assert find_cyclic_multi_target_loop(history) == lap


def test_find_cyclic_multi_target_loop_honors_explicit_max_window():
    targets = [f"file{i}.py" for i in range(10)]
    history = targets * 2
    # With small max_window=8, 20 entries cannot be detected (8 // 2 = 4 < 10)
    assert find_cyclic_multi_target_loop(history, max_window=8) is None
    # With max_window=44, 20 entries is detected
    assert find_cyclic_multi_target_loop(history, max_window=44) == targets



# --- v0.6 madde 1: progress-aware cyclic detection -------------------------

from agent.tools import canonical_cycle, extract_target, should_defer_cyclic_terminate


def test_canonical_cycle_is_rotation_independent():
    assert canonical_cycle(["c", "d", "a", "b"]) == ["a", "b", "c", "d"]
    assert canonical_cycle(["b", "c", "d", "a"]) == canonical_cycle(["a", "b", "c", "d"])


def test_identical_evidence_across_laps_is_still_cyclic():
    history = ["a.py", "b.py", "a.py", "b.py"]
    evidence = [("read_file", 1, "h1"), ("read_file", 1, "h2")] * 2
    assert find_cyclic_multi_target_loop(history, evidence=evidence) == ["a.py", "b.py"]


def test_changing_evidence_across_laps_is_progress_not_cyclic():
    """hMsRghV-style edit->test loop: same two targets, but the written
    content and the test output change every lap."""
    history = ["app.py", "test_app.py", "app.py", "test_app.py"]
    evidence = [
        ("write_file", 0, "sha1"), ("terminal_exec", 1, "out1"),
        ("write_file", 0, "sha2"), ("terminal_exec", 1, "out2"),
    ]
    assert find_cyclic_multi_target_loop(history, evidence=evidence) is None


def test_defer_cyclic_terminate_only_on_exit0_with_new_output():
    assert should_defer_cyclic_terminate(0, "new", {"old"}) is True
    assert should_defer_cyclic_terminate(0, "old", {"old"}) is False
    assert should_defer_cyclic_terminate(1, "new", {"old"}) is False


def test_extract_target_ignores_ip_inside_python_c():
    cmd = "python3 -c \"import socket; s=socket.socket(); s.connect(('10.0.0.5', 80))\""
    assert extract_target(cmd) is None
    assert extract_target("curl http://127.0.0.1:5000/") != "127.0.0.1"
    assert extract_target("python3 -c 'print(1)' src/app.py") == "src/app.py"
