from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from git_modifier.cli import (
    CommitInfo,
    compute_backward_schedule,
    compute_forward_schedule,
    validate_planned_gaps,
)
from git_modifier.office_hours import (
    OfficeHours,
    day_end,
    day_start,
    is_office_time,
    next_office_time,
    prev_office_time,
    random_office_time_on_day,
)

TZ = timezone(timedelta(hours=7))
OFFICE = OfficeHours(True, 9, 0, 18, 0, frozenset(range(5)))


def _day(
    hour: int,
    minute: int = 0,
    *,
    year: int = 2026,
    month: int = 7,
    day: int = 24,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def _commits(count: int) -> list[CommitInfo]:
    base = _day(0)
    return [
        CommitInfo("a" * 40, f"s{i:02d}", f"c{i}", base, base)
        for i in range(count)
    ]


def _boundary_hits(planned: list, office: OfficeHours) -> list[datetime]:
    hits: list[datetime] = []
    for item in planned:
        dt = item.new_date
        if dt == day_start(dt, office) or dt == day_end(dt, office):
            hits.append(dt)
    return hits


def _day_hop_boundary_hits(planned: list, office: OfficeHours) -> list[tuple[datetime, datetime]]:
    hits: list[tuple[datetime, datetime]] = []
    dates = [item.new_date for item in planned]
    for index in range(1, len(dates)):
        previous, current = dates[index - 1], dates[index]
        if current.date() == previous.date():
            continue
        if current == day_start(current, office) or previous == day_end(previous, office):
            hits.append((previous, current))
    return hits


def test_random_office_time_on_day_respects_gap_bounds() -> None:
    rng = random.Random(0)
    for _ in range(50):
        dt = random_office_time_on_day(_day(0), OFFICE, rng, 30, 120, from_start=True)
        assert is_office_time(dt, OFFICE)
        assert dt.hour > 9 or (dt.hour == 9 and dt.minute >= 30)


def test_next_office_time_does_not_snap_to_exact_start() -> None:
    rng = random.Random(1)
    dt = next_office_time(_day(7, 30), OFFICE, rng, 30, 120)
    assert dt.hour == 9
    assert dt.minute >= 30


def test_prev_office_time_does_not_snap_to_exact_end() -> None:
    rng = random.Random(2)
    dt = prev_office_time(_day(20, 0), OFFICE, rng, 30, 120)
    assert is_office_time(dt, OFFICE)
    assert dt.hour * 60 + dt.minute <= 18 * 60 - 30


def test_exact_window_edges_roll_to_adjacent_day() -> None:
    rng = random.Random(3)
    assert next_office_time(_day(18, 0), OFFICE, rng, 30, 120) > day_end(_day(18, 0), OFFICE)
    assert prev_office_time(_day(9, 0), OFFICE, rng, 30, 120) < day_start(_day(9, 0), OFFICE)


def test_schedules_never_use_exact_window_edges() -> None:
    for seed in range(50):
        for compute in (compute_forward_schedule, compute_backward_schedule):
            anchor = _day(8, 0) if compute is compute_forward_schedule else _day(20, 0)
            planned = compute(
                _commits(80),
                anchor,
                min_gap=30,
                max_gap=120,
                rng=random.Random(seed),
                office=OFFICE,
            )
            assert _boundary_hits(planned, OFFICE) == []


def test_schedules_are_monotonic_and_in_office_hours() -> None:
    for seed in range(20):
        for compute, anchor in (
            (compute_forward_schedule, _day(8, 0)),
            (compute_backward_schedule, _day(20, 0)),
        ):
            planned = compute(
                _commits(40),
                anchor,
                min_gap=30,
                max_gap=120,
                rng=random.Random(seed),
                office=OFFICE,
            )
            validate_planned_gaps(planned, 30, 120, OFFICE)
            dates = [item.new_date for item in planned]
            for index in range(1, len(dates)):
                assert dates[index] > dates[index - 1]
            for dt in dates:
                assert is_office_time(dt, OFFICE)
                assert dt != day_start(dt, OFFICE)
                assert dt != day_end(dt, OFFICE)


def test_same_day_gaps_stay_within_bounds() -> None:
    planned = compute_backward_schedule(
        _commits(80),
        end=_day(20, 0),
        min_gap=30,
        max_gap=120,
        rng=random.Random(42),
        office=OFFICE,
    )
    dates = [item.new_date for item in planned]
    for index in range(1, len(dates)):
        previous, current = dates[index - 1], dates[index]
        if current.date() != previous.date():
            continue
        gap = (current - previous).total_seconds() / 60
        assert 30 <= gap <= 120


def test_seed_is_reproducible() -> None:
    common = dict(
        commits=_commits(25),
        end=_day(20, 0),
        min_gap=30,
        max_gap=120,
        office=OFFICE,
    )
    first = compute_backward_schedule(**common, rng=random.Random(99))
    second = compute_backward_schedule(**common, rng=random.Random(99))
    assert [item.new_date for item in first] == [item.new_date for item in second]


def test_forward_schedule_skips_weekends() -> None:
    planned = compute_forward_schedule(
        _commits(20),
        start=datetime(2026, 7, 17, 10, 0, tzinfo=TZ),
        min_gap=30,
        max_gap=120,
        rng=random.Random(7),
        office=OFFICE,
    )
    assert all(item.new_date.weekday() < 5 for item in planned)


def test_day_hops_avoid_exact_window_edges() -> None:
    for seed in range(100):
        planned = compute_backward_schedule(
            _commits(80),
            end=_day(22, 0),
            min_gap=30,
            max_gap=120,
            rng=random.Random(seed),
            office=OFFICE,
        )
        assert _day_hop_boundary_hits(planned, OFFICE) == []
