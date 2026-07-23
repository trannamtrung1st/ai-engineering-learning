"""Rewrite commit author/committer dates on the current branch since merge-base."""

from __future__ import annotations

import argparse
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from git_modifier.config import load_flat_yaml
from git_modifier.office_hours import (
    OfficeHours,
    load_office_hours,
    next_office_time,
    prev_office_time,
    validate_office_times,
)

MIN_GAP_MINUTES = 30
MAX_GAP_MINUTES = 120


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    short: str
    subject: str
    author_date: datetime
    committer_date: datetime


@dataclass(frozen=True)
class PlannedCommit:
    info: CommitInfo
    new_date: datetime


def run_git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(stderr or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def resolve_base_branch(explicit: str | None) -> str:
    if explicit:
        return explicit

    for candidate in ("origin/main", "main", "origin/master", "master"):
        try:
            run_git("rev-parse", "--verify", candidate)
            return candidate
        except RuntimeError:
            continue

    raise RuntimeError(
        "Could not detect base branch. Pass --base (e.g. --base main)."
    )


def parse_git_timestamp(raw: str) -> datetime:
    return datetime.fromtimestamp(int(raw), tz=timezone.utc).astimezone()


def load_commits(merge_base: str, include_merges: bool, scope: str) -> list[CommitInfo]:
    if scope != "merge-base..HEAD":
        raise ValueError(
            f"Unsupported scope {scope!r}. Only 'merge-base..HEAD' is supported."
        )

    args = ["rev-list", "--reverse"]
    if not include_merges:
        args.append("--no-merges")
    args.extend([f"{merge_base}..HEAD"])

    shas = [line for line in run_git(*args).splitlines() if line]
    commits: list[CommitInfo] = []

    for sha in shas:
        raw = run_git(
            "log",
            "-1",
            "--format=%H%x1f%h%x1f%s%x1f%at%x1f%ct",
            sha,
        )
        full, short, subject, author_ts, committer_ts = raw.split("\x1f", 4)
        commits.append(
            CommitInfo(
                sha=full,
                short=short,
                subject=subject,
                author_date=parse_git_timestamp(author_ts),
                committer_date=parse_git_timestamp(committer_ts),
            )
        )

    return commits


def random_gap_minutes(min_gap: int, max_gap: int, rng: random.Random) -> int:
    if min_gap > max_gap:
        raise ValueError("--min-gap must be <= --max-gap")
    return rng.randint(min_gap, max_gap)


def compute_forward_schedule(
    commits: Iterable[CommitInfo],
    start: datetime,
    min_gap: int,
    max_gap: int,
    rng: random.Random,
    office: OfficeHours,
) -> list[PlannedCommit]:
    current = next_office_time(start, office) if office.enabled else start
    planned: list[PlannedCommit] = []

    for commit in commits:
        gap = random_gap_minutes(min_gap, max_gap, rng)
        candidate = current + timedelta(minutes=gap)
        if office.enabled:
            current = next_office_time(candidate, office)
        else:
            current = candidate
        planned.append(PlannedCommit(info=commit, new_date=current))

    return planned


def compute_backward_schedule(
    commits: Iterable[CommitInfo],
    end: datetime,
    min_gap: int,
    max_gap: int,
    rng: random.Random,
    office: OfficeHours,
) -> list[PlannedCommit]:
    commit_list = list(commits)
    if not commit_list:
        return []

    dates: list[datetime] = []
    current = prev_office_time(end, office) if office.enabled else end
    for _ in reversed(commit_list):
        gap = random_gap_minutes(min_gap, max_gap, rng)
        candidate = current - timedelta(minutes=gap)
        if office.enabled:
            current = prev_office_time(candidate, office)
        else:
            current = candidate
        dates.append(current)
    dates.reverse()

    return [
        PlannedCommit(info=commit, new_date=date)
        for commit, date in zip(commit_list, dates)
    ]


def format_git_date(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S %z")


def resolve_anchor(anchor: str | None) -> datetime:
    if anchor is None:
        return datetime.now().astimezone()

    value = str(anchor).strip()
    if not value or value.lower() == "now":
        return datetime.now().astimezone()

    match = re.match(
        r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) ([+-]\d{4})$",
        value,
    )
    if not match:
        raise ValueError(
            "Invalid anchor. Leave empty for now, or use 'YYYY-MM-DD HH:MM:SS +ZZZZ'."
        )

    date_part, time_part, offset_part = match.groups()
    sign = 1 if offset_part[0] == "+" else -1
    offset_hours = int(offset_part[1:3])
    offset_minutes = int(offset_part[3:5])
    tz = timezone(sign * timedelta(hours=offset_hours, minutes=offset_minutes))
    return datetime.strptime(
        f"{date_part} {time_part}",
        "%Y-%m-%d %H:%M:%S",
    ).replace(tzinfo=tz)


def normalize_direction(raw: str | None) -> str:
    if raw is None:
        return "forward"

    value = str(raw).strip().lower()
    if value in ("forward", "add", "+"):
        return "forward"
    if value in ("backward", "subtract", "-"):
        return "backward"

    raise ValueError(
        "Invalid direction. Use forward (anchor + gaps) or backward (anchor − gaps)."
    )


def describe_direction(direction: str) -> str:
    if direction == "forward":
        return "anchor + random gaps"
    return "anchor − random gaps"


def is_merge_commit(sha: str) -> bool:
    parents = run_git("rev-list", "--parents", "-n", "1", sha).split()
    return len(parents) > 2


def validate_planned_gaps(
    planned: list[PlannedCommit],
    min_gap: int,
    max_gap: int,
    office: OfficeHours,
) -> None:
    if len(planned) < 2:
        if planned and office.enabled:
            validate_office_times(planned, office)
        return

    for index in range(1, len(planned)):
        if planned[index].new_date <= planned[index - 1].new_date:
            raise ValueError("Planned dates must strictly increase from oldest to newest.")

        if office.enabled:
            continue

        gap_minutes = (
            planned[index].new_date - planned[index - 1].new_date
        ).total_seconds() / 60
        if gap_minutes < min_gap or gap_minutes > max_gap:
            raise ValueError(
                "Planned gap between commits "
                f"{planned[index - 1].info.short} and {planned[index].info.short} "
                f"is {gap_minutes:.0f} minutes (expected {min_gap}–{max_gap})."
            )

    if office.enabled:
        validate_office_times(planned, office)


def ensure_clean_worktree() -> None:
    status = run_git("status", "--porcelain", "--untracked-files=no")
    if status:
        raise RuntimeError(
            "Working tree has staged or modified tracked files. "
            "Commit or stash them before --apply."
        )


def print_plan(
    merge_base: str,
    base_branch: str,
    scope: str,
    include_merges: bool,
    direction: str,
    anchor: datetime,
    office: OfficeHours,
    min_gap: int,
    max_gap: int,
    planned: list[PlannedCommit],
) -> None:
    print(f"Base branch:     {base_branch}")
    print(f"Merge-base:      {merge_base[:12]}")
    print(f"Scope:           {scope}")
    print(f"Include merges:  {include_merges}")
    print(f"Direction:       {describe_direction(direction)}")
    print(f"Anchor:          {format_git_date(anchor)}")
    print(f"Office hours:    {office.describe()}")
    print(f"Gap range:       {min_gap}–{max_gap} minutes (random per commit)")
    print(f"Commits to touch: {len(planned)}")
    print()
    print(f"{'#':>3}  {'SHA':<10}  {'Old author date':<26}  {'New date':<26}  Subject")
    print("-" * 110)

    for index, item in enumerate(planned, start=1):
        old = format_git_date(item.info.author_date)
        new = format_git_date(item.new_date)
        subject = item.info.subject
        if len(subject) > 42:
            subject = subject[:39] + "..."
        print(
            f"{index:>3}  {item.info.short:<10}  {old:<26}  {new:<26}  {subject}"
        )

    if len(planned) >= 2:
        span = planned[-1].new_date - planned[0].new_date
        print()
        print(f"Total span: {span} ({planned[0].new_date} → {planned[-1].new_date})")


def write_env_filter_script(date_map_file: Path) -> Path:
    script = Path(tempfile.mktemp(prefix="git-modifier-env-filter-", suffix=".sh"))
    script.write_text(
        f"""#!/bin/sh
MAP={date_map_file.as_posix()}
sha="$GIT_COMMIT"
date_line=$(grep "^${{sha}} " "$MAP" || true)
if [ -n "$date_line" ]; then
  date="${{date_line#* }}"
  export GIT_AUTHOR_DATE="$date"
  export GIT_COMMITTER_DATE="$date"
fi
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def make_backup_branch_name(current_branch: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", current_branch).strip("-")
    if not safe:
        safe = "head"
    return f"git-modifier-backup/{safe}-before-date-rewrite"


def create_backup_branch(current_branch: str) -> str:
    backup_branch = make_backup_branch_name(current_branch)
    run_git("branch", "-f", backup_branch)
    print(f"Created backup branch: {backup_branch}")
    return backup_branch


def apply_plan(merge_base: str, planned: list[PlannedCommit]) -> None:
    ensure_clean_worktree()

    current_branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
    backup_branch = create_backup_branch(current_branch)

    temp_dir = Path(tempfile.mkdtemp(prefix="git-modifier-dates-"))
    date_map_file = temp_dir / "sha-dates.map"
    date_map_file.write_text(
        "\n".join(
            f"{item.info.sha} {format_git_date(item.new_date)}" for item in planned
        )
        + "\n",
        encoding="utf-8",
    )

    env_filter = write_env_filter_script(date_map_file)
    merge_count = sum(1 for item in planned if is_merge_commit(item.info.sha))
    if merge_count:
        print(f"Rewriting {len(planned)} commits ({merge_count} merge) via filter-branch...")
    else:
        print(f"Rewriting {len(planned)} commits via filter-branch...")

    env = os.environ.copy()
    env["FILTER_BRANCH_SQUELCH_WARNING"] = "1"

    try:
        subprocess.run(
            [
                "git",
                "filter-branch",
                "-f",
                "--env-filter",
                f". {env_filter.as_posix()}",
                "--",
                f"{merge_base}..HEAD",
            ],
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        print(
            "\nfilter-branch failed. Recover with:\n"
            f"  git reset --hard {backup_branch}\n",
            file=sys.stderr,
        )
        raise SystemExit(exc.returncode) from exc
    finally:
        env_filter.unlink(missing_ok=True)
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("\nDone. Verify with:")
    print(f"  git log --format='%h %ad %s' {merge_base}..HEAD")
    print(
        "\nOptional cleanup of filter-branch backup refs:\n"
        f"  git update-ref -d refs/original/refs/heads/{current_branch}"
    )


def resolve_config_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def load_settings(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    settings = load_flat_yaml(config_path)
    settings["_config_path"] = str(config_path)
    return settings


def pick_value(
    cli_value: Any,
    config: dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    if cli_value is not None:
        return cli_value
    if key in config:
        return config[key]
    return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Distribute commit timestamps on the current branch since merge-base. "
            "Each consecutive gap is random between --min-gap and --max-gap minutes."
        )
    )
    parser.add_argument(
        "--config",
        required=True,
        help="YAML config file (required).",
    )
    parser.add_argument(
        "--base",
        help="Base branch name (overrides config; default: auto-detect main/master).",
    )
    parser.add_argument(
        "--scope",
        help="Commit range (overrides config; default: merge-base..HEAD).",
    )
    parser.add_argument(
        "--include-merges",
        action="store_true",
        default=None,
        help="Include merge commits (overrides config).",
    )
    parser.add_argument(
        "--no-include-merges",
        action="store_true",
        help="Exclude merge commits (overrides config).",
    )
    parser.add_argument(
        "--direction",
        choices=("forward", "backward", "add", "subtract", "+", "-"),
        help=(
            "forward/add/+: anchor + random gaps per commit; "
            "backward/subtract/−: anchor − random gaps per commit."
        ),
    )
    parser.add_argument(
        "--anchor",
        help=(
            "Anchor datetime: 'YYYY-MM-DD HH:MM:SS +ZZZZ'. "
            "Omit or leave empty in config for current time (now)."
        ),
    )
    parser.add_argument(
        "--min-gap",
        type=int,
        help=f"Minimum minutes between commits (default: {MIN_GAP_MINUTES}).",
    )
    parser.add_argument(
        "--max-gap",
        type=int,
        help=f"Maximum minutes between commits (default: {MAX_GAP_MINUTES}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducible gap sequence.",
    )
    parser.add_argument(
        "--office-hours",
        action="store_true",
        default=None,
        dest="office_hours_enabled",
        help="Restrict commit times to office hours (overrides config).",
    )
    parser.add_argument(
        "--no-office-hours",
        action="store_false",
        dest="office_hours_enabled",
        help="Disable office-hours restriction (overrides config).",
    )
    parser.add_argument(
        "--office-hours-start",
        dest="office_hours_start",
        help="Office day start time HH:MM (default: 09:00).",
    )
    parser.add_argument(
        "--office-hours-end",
        dest="office_hours_end",
        help="Office day end time HH:MM (default: 18:00).",
    )
    parser.add_argument(
        "--office-hours-weekdays",
        dest="office_hours_weekdays",
        help="Office weekdays: mon-fri, mon,tue,..., or 0-4 (0=Mon).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=None,
        help="Rewrite history via filter-branch (creates a backup branch).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry-run even if config has apply: true.",
    )
    return parser


def resolve_runtime_options(args: argparse.Namespace) -> dict[str, Any]:
    config_path = resolve_config_path(args.config)
    config = load_settings(config_path)

    if args.no_include_merges:
        include_merges = False
    elif args.include_merges is True:
        include_merges = True
    else:
        include_merges = bool(pick_value(None, config, "include_merges", False))

    if args.dry_run:
        apply = False
    elif args.apply is True:
        apply = True
    else:
        apply = bool(pick_value(None, config, "apply", False))

    min_gap = pick_value(args.min_gap, config, "min_gap", MIN_GAP_MINUTES)
    max_gap = pick_value(args.max_gap, config, "max_gap", MAX_GAP_MINUTES)
    if min_gap > max_gap:
        raise ValueError("--min-gap must be <= --max-gap")

    direction = normalize_direction(
        pick_value(args.direction, config, "direction", "forward")
    )
    office = load_office_hours(config, args)

    return {
        "config_path": config_path,
        "base": pick_value(args.base, config, "base"),
        "scope": pick_value(args.scope, config, "scope", "merge-base..HEAD"),
        "include_merges": include_merges,
        "direction": direction,
        "anchor": pick_value(args.anchor, config, "anchor"),
        "office": office,
        "min_gap": min_gap,
        "max_gap": max_gap,
        "seed": pick_value(args.seed, config, "seed"),
        "apply": apply,
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    options = resolve_runtime_options(args)

    repo_root = run_git("rev-parse", "--show-toplevel")
    os.chdir(repo_root)

    print(f"Config:          {options['config_path']}")
    print()

    base_branch = resolve_base_branch(options["base"])
    merge_base = run_git("merge-base", "HEAD", base_branch)
    commits = load_commits(
        merge_base,
        options["include_merges"],
        options["scope"],
    )

    if not commits:
        print(f"No commits found in {options['scope']} (merge-base {merge_base[:12]}).")
        return

    rng = random.Random(options["seed"])
    anchor = resolve_anchor(options["anchor"])

    if options["direction"] == "forward":
        planned = compute_forward_schedule(
            commits,
            start=anchor,
            min_gap=options["min_gap"],
            max_gap=options["max_gap"],
            rng=rng,
            office=options["office"],
        )
    else:
        planned = compute_backward_schedule(
            commits,
            end=anchor,
            min_gap=options["min_gap"],
            max_gap=options["max_gap"],
            rng=rng,
            office=options["office"],
        )

    print_plan(
        merge_base=merge_base,
        base_branch=base_branch,
        scope=options["scope"],
        include_merges=options["include_merges"],
        direction=options["direction"],
        anchor=anchor,
        office=options["office"],
        min_gap=options["min_gap"],
        max_gap=options["max_gap"],
        planned=planned,
    )

    validate_planned_gaps(
        planned,
        options["min_gap"],
        options["max_gap"],
        options["office"],
    )

    if not options["apply"]:
        print()
        print("Dry run only. Set apply: true in config or pass --apply to rewrite dates.")
        return

    print()
    apply_plan(merge_base, planned)
