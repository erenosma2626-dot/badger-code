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
