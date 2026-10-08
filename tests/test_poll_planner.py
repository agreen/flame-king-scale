"""Tests for the idle/fast polling planner."""

import pytest

from custom_components.flame_king_scale.polling import (
    MAX_CONSECUTIVE_FAILURES,
    MAX_FAST_SECONDS,
    MIN_FAST_POLL_SECONDS,
    MIN_QUIET_POLLS,
    PollMode,
    PollPlanner,
    quiet_polls_needed,
)

TOLERANCE = 20


def success(planner: PollPlanner, raw: int, *, now: float = 0.0, **kw) -> None:
    planner.record_success(
        raw,
        tolerance=TOLERANCE,
        flowing=kw.pop("flowing", False),
        quiet_needed=kw.pop("quiet_needed", 5),
        now=now,
    )


@pytest.mark.parametrize(
    ("window", "gap", "expected"),
    [
        (300, 60, 5),  # 300 / (60 + 5) = 4.6 -> 5
        (300, 30, 9),  # 300 / 35 = 8.6 -> 9
        (300, 120, 4),  # 300 / 125 = 2.4 -> raised to the floor
        (600, 60, 10),
        (0, 60, MIN_QUIET_POLLS),
        (300, 5, 15),  # a gap below the minimum is treated as the minimum
    ],
)
def test_quiet_polls_needed(window: float, gap: float, expected: int) -> None:
    assert quiet_polls_needed(window, gap) == expected


def test_first_reading_is_only_a_baseline() -> None:
    planner = PollPlanner()
    success(planner, 1000)
    assert planner.mode is PollMode.IDLE
    assert planner.anchor_raw == 1000


def test_idle_change_starts_fast_polling() -> None:
    planner = PollPlanner()
    success(planner, 1000)
    success(planner, 1100, now=3600)
    assert planner.mode is PollMode.FAST
    assert planner.quiet_polls == 0
    assert planner.anchor_raw == 1100


def test_idle_reanchors_every_poll_so_slow_drift_accumulates() -> None:
    planner = PollPlanner()
    success(planner, 1000)
    success(planner, 1010, now=1)  # within tolerance
    assert planner.anchor_raw == 1010
    success(planner, 1025, now=2)  # 15 from the new anchor: still quiet
    assert planner.mode is PollMode.IDLE


def test_fast_mode_ends_after_enough_quiet_polls() -> None:
    planner = PollPlanner()
    success(planner, 1000)
    success(planner, 2000, now=1)
    assert planner.mode is PollMode.FAST
    for i in range(4):
        success(planner, 2005, now=2 + i)
        assert planner.mode is PollMode.FAST
    success(planner, 2005, now=10)
    assert planner.mode is PollMode.IDLE
    assert planner.anchor_raw == 2005


def test_fast_mode_keeps_its_baseline_until_a_real_change() -> None:
    planner = PollPlanner()
    success(planner, 1000)
    success(planner, 2000, now=1)
    success(planner, 2010, now=2)  # quiet; anchor must not creep
    assert planner.anchor_raw == 2000
    success(planner, 2030, now=3)  # 30 from the fixed anchor: real change
    assert planner.quiet_polls == 0
    assert planner.anchor_raw == 2030


def test_flow_keeps_fast_mode_alive_without_a_weight_change() -> None:
    planner = PollPlanner()
    success(planner, 1000)
    success(planner, 2000, now=1)
    for i in range(10):
        success(planner, 2001, now=2 + i, flowing=True)
    assert planner.mode is PollMode.FAST
    assert planner.quiet_polls == 0


def test_activity_resets_the_quiet_count() -> None:
    planner = PollPlanner()
    success(planner, 1000)
    success(planner, 2000, now=1)
    for i in range(3):
        success(planner, 2000, now=2 + i)
    assert planner.quiet_polls == 3
    success(planner, 3000, now=6)
    assert planner.quiet_polls == 0


def test_seed_fast_starts_or_restarts_the_count() -> None:
    planner = PollPlanner()
    planner.seed_fast(now=5)
    assert planner.mode is PollMode.FAST
    assert planner.fast_since == 5
    planner.quiet_polls = 3
    planner.seed_fast(now=50)  # pressing again restarts the count only
    assert planner.quiet_polls == 0
    assert planner.fast_since == 5


def test_failures_neither_count_as_quiet_nor_move_the_baseline() -> None:
    planner = PollPlanner()
    success(planner, 1000)
    success(planner, 2000, now=1)
    success(planner, 2000, now=2)
    assert planner.quiet_polls == 1
    assert planner.record_failure() is False
    assert planner.record_failure() is False
    assert planner.quiet_polls == 1
    assert planner.anchor_raw == 2000
    assert planner.mode is PollMode.FAST


def test_repeated_failures_end_fast_polling() -> None:
    planner = PollPlanner()
    planner.seed_fast(now=0)
    results = [planner.record_failure() for _ in range(MAX_CONSECUTIVE_FAILURES)]
    assert results == [False] * (MAX_CONSECUTIVE_FAILURES - 1) + [True]
    assert planner.mode is PollMode.IDLE
    assert planner.quiet_polls == 0


def test_a_success_clears_the_failure_streak() -> None:
    planner = PollPlanner()
    planner.seed_fast(now=0)
    planner.record_failure()
    planner.record_failure()
    success(planner, 1000, now=1)
    assert planner.consecutive_failures == 0
    assert planner.record_failure() is False  # the streak starts over


def test_failures_in_idle_mode_never_change_the_mode() -> None:
    planner = PollPlanner()
    for _ in range(10):
        assert planner.record_failure() is False
    assert planner.mode is PollMode.IDLE


def test_fast_polling_has_a_hard_time_cap() -> None:
    planner = PollPlanner()
    success(planner, 1000)
    success(planner, 2000, now=0)
    success(planner, 3000, now=MAX_FAST_SECONDS + 1)  # still changing, but capped
    assert planner.mode is PollMode.IDLE
    assert planner.anchor_raw == 3000


def test_next_interval() -> None:
    planner = PollPlanner()
    assert planner.next_interval(3600, 60) == 3600
    planner.seed_fast(now=0)
    assert planner.next_interval(3600, 60) == 60
    assert planner.next_interval(3600, 5) == MIN_FAST_POLL_SECONDS
