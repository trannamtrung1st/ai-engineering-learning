"""Run-record schema_version gate (proposal §3, §13 items 57–58b)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import (
    CURRENT_RUN_SCHEMA_VERSION,
    FileRunStore,
    UNSUPPORTED_RUN_SCHEMA_MESSAGE,
    UnsupportedRunSchemaVersionError,
    validate_run_schema_version,
)
from tests.helpers import minimal_invocation

_EMPTY_SNAPSHOT_BINDING = {
    "workspace": "/workspace",
    "resource_digests": [],
    "skill_digests": [],
}


def _sample_plan() -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    return Plan(
        id="plan-001",
        revision=0,
        output_goal="Deliver the output.",
        items={"item-root": root},
    )


def _create_run(store: FileRunStore, run_id: str = "run-20260101T000001-000001") -> dict:
    return store.create_run(
        run_id,
        plan=_sample_plan(),
        resolved_config={"limits": {}},
        input_digest="input-a",
        output_goal_digest="goal-b",
        context_spec_digest="0" * 64,
        context_snapshot_digest="1" * 64,
        context_snapshot_binding={
            **_EMPTY_SNAPSHOT_BINDING,
            "workspace": str(store.root),
        },
        workspace=str(store.root),
        invocation=minimal_invocation(store.root),
    )


def test_create_run_writes_current_schema_version(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run = _create_run(store)
    assert run["schema_version"] == CURRENT_RUN_SCHEMA_VERSION
    loaded = store.load_run("run-20260101T000001-000001")
    assert loaded["schema_version"] == CURRENT_RUN_SCHEMA_VERSION


def test_missing_schema_version_rejected_with_recreate_message(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    run_path = tmp_path / "run-20260101T000001-000001" / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    del payload["schema_version"]
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(UnsupportedRunSchemaVersionError, match=UNSUPPORTED_RUN_SCHEMA_MESSAGE):
        store.load_run("run-20260101T000001-000001")


def test_unsupported_schema_version_rejected_with_recreate_message(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    run_path = tmp_path / "run-20260101T000001-000001" / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["schema_version"] = CURRENT_RUN_SCHEMA_VERSION + 1
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(UnsupportedRunSchemaVersionError, match=UNSUPPORTED_RUN_SCHEMA_MESSAGE):
        store.load_run("run-20260101T000001-000001")


def test_schema_version_gate_runs_before_nested_field_errors(tmp_path: Path) -> None:
    """Legacy records fail at schema_version before incidental nested errors (§13 58b)."""

    store = FileRunStore(tmp_path)
    run_dir = tmp_path / "run-20260101T000099-000099"
    run_dir.mkdir()
    # Intentionally omit schema_version and also omit required nested fields.
    (run_dir / "run.json").write_text(json.dumps({"id": "run-20260101T000099-000099"}), encoding="utf-8")

    with pytest.raises(UnsupportedRunSchemaVersionError, match=UNSUPPORTED_RUN_SCHEMA_MESSAGE) as exc_info:
        store.load_run("run-20260101T000099-000099")
    assert "digests" not in str(exc_info.value).lower()
    assert "context_snapshot" not in str(exc_info.value).lower()


def test_validate_run_schema_version_rejects_non_int() -> None:
    with pytest.raises(UnsupportedRunSchemaVersionError):
        validate_run_schema_version({"schema_version": "2"})
    with pytest.raises(UnsupportedRunSchemaVersionError):
        validate_run_schema_version({"schema_version": True})


def test_schema_version_alone_does_not_reject_list_binding_shape(tmp_path: Path) -> None:
    """Completing the schema gate must still load legacy list/absolute bindings."""

    store = FileRunStore(tmp_path)
    _create_run(store)
    loaded = store.load_run("run-20260101T000001-000001")
    binding = loaded["context_snapshot_binding"]
    assert isinstance(binding["resource_digests"], list)
    assert isinstance(binding.get("workspace"), str)
