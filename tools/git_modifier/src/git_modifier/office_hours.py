"""Office-hours constraints for commit timestamp scheduling."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


WEEKDAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


@dataclass(frozen=True)
class OfficeHours:
    enabled: bool
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    weekdays: frozenset[int]

    def describe(self) -> str:
        if not self.enabled:
            return "disabled"

        days = weekday_label(sorted(self.weekdays))
        return (
            f"{self.start_hour:02d}:{self.start_minute:02d}"
            f"–{self.end_hour:02d}:{self.end_minute:02d}, {days}"
        )


def weekday_label(days: list[int]) -> str:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if days == list(range(5)):
        return "Mon–Fri"
    if days == list(range(7)):
        return "Mon–Sun"
    return ", ".join(names[day] for day in days)


def parse_clock(value: str, field_name: str) -> tuple[int, int]:
    match = re.match(r"^(\d{1,2}):(\d{2})$", value.strip())
    if not match:
        raise ValueError(
            f"Invalid {field_name} {value!r}. Use 24-hour 'HH:MM' (e.g. '09:00')."
        )

    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid {field_name} {value!r}.")
    return hour, minute


def parse_weekdays(raw: str | None) -> frozenset[int]:
    if raw is None or not str(raw).strip():
        return frozenset(range(5))

    value = str(raw).strip().lower()
    if value in ("mon-fri", "weekdays", "weekday"):
        return frozenset(range(5))
    if value in ("mon-sun", "daily", "everyday"):
        return frozenset(range(7))

    range_match = re.match(r"^(\w+)\s*-\s*(\w+)$", value)
    if range_match:
        start = WEEKDAY_ALIASES.get(range_match.group(1))
        end = WEEKDAY_ALIASES.get(range_match.group(2))
        if start is None or end is None:
            raise ValueError(f"Invalid office_hours_weekdays range {raw!r}.")
        if start <= end:
            return frozenset(range(start, end + 1))
        return frozenset(list(range(start, 7)) + list(range(0, end + 1)))

    days: set[int] = set()
    for token in re.split(r"[\s,]+", value):
        if not token:
            continue
        if token.isdigit():
            day = int(token)
            if day == 7:
                day = 0
            if day < 0 or day > 6:
                raise ValueError(f"Invalid weekday number {token!r} (use 0=Mon .. 6=Sun).")
            days.add(day)
            continue

        mapped = WEEKDAY_ALIASES.get(token)
        if mapped is None:
            raise ValueError(f"Invalid weekday {token!r}.")
        days.add(mapped)

    if not days:
        raise ValueError("office_hours_weekdays must list at least one weekday.")
    return frozenset(days)


def load_office_hours(config: dict[str, Any], args: Any) -> OfficeHours:
    enabled = pick_bool(args, config, "office_hours_enabled", False)
    start_raw = pick_str(args, config, "office_hours_start", "09:00")
    end_raw = pick_str(args, config, "office_hours_end", "18:00")
    weekdays_raw = pick_str(args, config, "office_hours_weekdays", "mon-fri")

    start_hour, start_minute = parse_clock(start_raw, "office_hours_start")
    end_hour, end_minute = parse_clock(end_raw, "office_hours_end")
    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute
    if start_total >= end_total:
        raise ValueError("office_hours_start must be earlier than office_hours_end.")

    return OfficeHours(
        enabled=enabled,
        start_hour=start_hour,
        start_minute=start_minute,
        end_hour=end_hour,
        end_minute=end_minute,
        weekdays=parse_weekdays(weekdays_raw),
    )


def pick_bool(args: Any, config: dict[str, Any], key: str, default: bool) -> bool:
    cli_value = getattr(args, key, None)
    if cli_value is not None:
        return bool(cli_value)
    if key in config and config[key] is not None:
        return bool(config[key])
    return default


def pick_str(args: Any, config: dict[str, Any], key: str, default: str) -> str:
    cli_value = getattr(args, key, None)
    if cli_value is not None:
        return str(cli_value)
    if key in config and config[key] is not None:
        return str(config[key])
    return default


def day_start(dt: datetime, office: OfficeHours) -> datetime:
    return dt.replace(
        hour=office.start_hour,
        minute=office.start_minute,
        second=0,
        microsecond=0,
    )


def day_end(dt: datetime, office: OfficeHours) -> datetime:
    return dt.replace(
        hour=office.end_hour,
        minute=office.end_minute,
        second=0,
        microsecond=0,
    )


def office_window_minutes(office: OfficeHours) -> int:
    start_total = office.start_hour * 60 + office.start_minute
    end_total = office.end_hour * 60 + office.end_minute
    return end_total - start_total


def gap_bounded_offset_minutes(
    window: int,
    min_gap: int,
    max_gap: int,
    rng: random.Random,
) -> int:
    if window <= 0:
        return 0
    if window <= min_gap:
        return rng.randint(0, window)
    low = min_gap
    high = min(max_gap, window)
    return rng.randint(low, high)


def random_office_time_on_day(
    day: datetime,
    office: OfficeHours,
    rng: random.Random,
    min_gap: int,
    max_gap: int,
    *,
    from_start: bool,
) -> datetime:
    """Pick a random in-hours time on ``day``'s calendar date."""
    start = day_start(day, office)
    end = day_end(day, office)
    window = office_window_minutes(office)
    offset = gap_bounded_offset_minutes(window, min_gap, max_gap, rng)
    if from_start:
        return start + timedelta(minutes=offset)
    return end - timedelta(minutes=offset)


def is_office_time(dt: datetime, office: OfficeHours) -> bool:
    if dt.weekday() not in office.weekdays:
        return False
    start = day_start(dt, office)
    end = day_end(dt, office)
    return start <= dt <= end


def next_office_time(
    dt: datetime,
    office: OfficeHours,
    rng: random.Random,
    min_gap: int,
    max_gap: int,
) -> datetime:
    current = dt.replace(second=0, microsecond=0)
    for _ in range(366 * 2):
        if current.weekday() in office.weekdays:
            start = day_start(current, office)
            end = day_end(current, office)
            if current < start:
                return random_office_time_on_day(
                    current, office, rng, min_gap, max_gap, from_start=True
                )
            if current < end:
                return current
        next_day = day_start(current + timedelta(days=1), office)
        while next_day.weekday() not in office.weekdays:
            next_day = day_start(next_day + timedelta(days=1), office)
        return random_office_time_on_day(
            next_day, office, rng, min_gap, max_gap, from_start=True
        )
    raise ValueError("Could not find a valid office-hours timestamp going forward.")


def prev_office_time(
    dt: datetime,
    office: OfficeHours,
    rng: random.Random,
    min_gap: int,
    max_gap: int,
) -> datetime:
    current = dt.replace(second=0, microsecond=0)
    for _ in range(366 * 2):
        if current.weekday() in office.weekdays:
            start = day_start(current, office)
            end = day_end(current, office)
            if current > end:
                return random_office_time_on_day(
                    current, office, rng, min_gap, max_gap, from_start=False
                )
            if current > start:
                return current
        prev_day = day_end(current - timedelta(days=1), office)
        while prev_day.weekday() not in office.weekdays:
            prev_day = day_end(prev_day - timedelta(days=1), office)
        return random_office_time_on_day(
            prev_day, office, rng, min_gap, max_gap, from_start=False
        )
    raise ValueError("Could not find a valid office-hours timestamp going backward.")


def validate_office_times(planned: list[Any], office: OfficeHours) -> None:
    for item in planned:
        if not is_office_time(item.new_date, office):
            raise ValueError(
                "Planned commit "
                f"{item.info.short} at {item.new_date} is outside office hours "
                f"({office.describe()})."
            )
