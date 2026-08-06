"""Tests for stale run reconciliation and workspace hygiene."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.run_lifecycle_reconciliation import (
    cleanup_staging_dirs,
    list_incomplete_run_dirs,
    reconcile_stale_running_run,
    workspace_diagnostics,
)
from top_down_planning.persistence import FileRunStore
from tests.unit.test_operational_failures import _create_run


def test_reconcile_stale_running_run_requires_orphan_agents_by_default(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T002001-002001", phase=PLANNING)

    with patch(
        "top_down_planning.orchestrator.run_lifecycle_reconciliation.is_run_orchestrator_alive",
        return_value=False,
    ):
        reconciled = reconcile_stale_running_run(store, "run-20260101T002001-002001")

    assert reconciled is False
    assert store.load_run("run-20260101T002001-002001")["status"] == "running"


def test_reconcile_stale_running_run_pauses_when_orphans_present(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T002011-002011", phase=PLANNING)

    with patch(
        "top_down_planning.orchestrator.run_lifecycle_reconciliation.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.orchestrator.run_lifecycle_reconciliation.scan_orphan_agent_pids",
            return_value=[4242],
        ):
            reconciled = reconcile_stale_running_run(store, "run-20260101T002011-002011")

    assert reconciled is True
    run = store.load_run("run-20260101T002011-002011")
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "orchestrator_interrupted"
    assert run["stop"]["details"]["orphan_agent_pids"] == [4242]
    events = store.load_events("run-20260101T002011-002011")
    assert any(event.get("type") == "run_reconciled" for event in events)


def test_reconcile_stale_running_run_force_without_orphans(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T002012-002012", phase=PLANNING)

    with patch(
        "top_down_planning.orchestrator.run_lifecycle_reconciliation.is_run_orchestrator_alive",
        return_value=False,
    ):
        reconciled = reconcile_stale_running_run(
            store,
            "run-20260101T002012-002012",
            require_orphan_agents=False,
        )

    assert reconciled is True
    assert store.load_run("run-20260101T002012-002012")["status"] == "paused"


def test_reconcile_stale_running_run_skips_live_owner(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T002002-002002", phase=PLANNING)

    with patch(
        "top_down_planning.orchestrator.run_lifecycle_reconciliation.is_run_orchestrator_alive",
        return_value=True,
    ):
        reconciled = reconcile_stale_running_run(store, "run-20260101T002002-002002")

    assert reconciled is False
    assert store.load_run("run-20260101T002002-002002")["status"] == "running"


def test_list_incomplete_run_dirs_reports_missing_run_json(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    ghost = tmp_path / "run-20260101T002003-002003"
    ghost.mkdir()
    (ghost / "events.jsonl").write_text("", encoding="utf-8")

    assert list_incomplete_run_dirs(store) == ["run-20260101T002003-002003"]


def test_cleanup_staging_dirs_removes_creating_directories(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    staging = tmp_path / ".creating-run-20260101T002004-002004"
    staging.mkdir()
    (staging / "run.json").write_text("{}", encoding="utf-8")

    removed = cleanup_staging_dirs(store)

    assert removed == [".creating-run-20260101T002004-002004"]
    assert not staging.exists()


def test_workspace_diagnostics_splits_idle_and_interrupted_running(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T002005-002005", phase=PLANNING)
    _create_run(store, run_id="run-20260101T002006-002006", phase=PLANNING)

    def fake_orphans(run_id: str, **_kwargs: object) -> list[int]:
        if run_id == "run-20260101T002006-002006":
            return [5151]
        return []

    with patch(
        "top_down_planning.orchestrator.run_lifecycle_reconciliation.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.orchestrator.run_lifecycle_reconciliation.scan_orphan_agent_pids",
            side_effect=fake_orphans,
        ):
            diagnostics = workspace_diagnostics(store)

    assert diagnostics["idle_running_run_ids"] == ["run-20260101T002005-002005"]
    assert diagnostics["interrupted_running_run_ids"] == ["run-20260101T002006-002006"]
