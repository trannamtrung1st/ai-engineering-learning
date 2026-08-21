"""Commit/crash helpers shared by persistence and Slice 7 regressions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core_tools.persistence import atomic_write_json
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec


def _multi_file_commit(store: FileRunStore, run_id: str) -> None:
    from top_down_planning.persistence.snapshot_bindings import bind_run_digests_for_plan_update

    run = store.load_run(run_id)
    plan = store.load_plan(run_id)
    run_expected = int(run["revision"])
    plan_expected = int(plan["revision"])
    plan = dict(plan)
    plan["revision"] = plan_expected + 1
    run = bind_run_digests_for_plan_update(
        {**dict(run), "revision": run_expected + 1},
        plan,
    )
    store.commit(
        run_id,
        CommitSpec(
            run=run,
            run_expected_revision=run_expected,
            plan=plan,
            plan_expected_revision=plan_expected,
            events=[{"type": "test_commit", "run_id": run_id}],
        ),
    )


def _crash_before_dest_replace_count(replace_count: int) -> Any:
    original_replace = Path.replace
    calls = 0

    def patched_replace(self: Path, target: Path) -> Path:
        nonlocal calls
        self_parts = self.parts
        target_parts = target.parts
        if any(part.startswith(".txn-") for part in self_parts) and not any(
            part.startswith(".txn-") for part in target_parts
        ):
            calls += 1
            if calls == replace_count:
                raise OSError("simulated crash")
        return original_replace(self, target)

    return patched_replace


def _crash_after_dest_replace_count(replace_count: int) -> Any:
    original_replace = Path.replace
    calls = 0

    def patched_replace(self: Path, target: Path) -> Path:
        nonlocal calls
        result = original_replace(self, target)
        self_parts = self.parts
        target_parts = target.parts
        if any(part.startswith(".txn-") for part in self_parts) and not any(
            part.startswith(".txn-") for part in target_parts
        ):
            calls += 1
            if calls == replace_count:
                raise OSError("simulated crash")
        return result

    return patched_replace


def _crash_before_appending_events() -> Any:
    original_write = atomic_write_json

    def patched_write(path: Path, payload: dict[str, Any]) -> None:
        original_write(path, payload)
        if path.name == "journal.json" and payload.get("status") == "appending_events":
            raise OSError("simulated crash")

    return patched_write


def _crash_on_appending_events_journal_write() -> Any:
    original_write = atomic_write_json

    def patched_write(path: Path, payload: dict[str, Any]) -> None:
        if path.name == "journal.json" and payload.get("status") == "appending_events":
            raise OSError("simulated crash")
        original_write(path, payload)

    return patched_write
