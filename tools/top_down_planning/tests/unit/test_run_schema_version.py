"""Run-record schema_version gate (proposal §3, §13 items 57–58b)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import (
    CURRENT_RUN_SCHEMA_VERSION,
    FileRunStore,
    PersistenceError,
    UNSUPPORTED_RUN_SCHEMA_MESSAGE,
    UnsupportedRunSchemaVersionError,
    validate_run_schema_version,
)
from tests.helpers import minimal_invocation

_EMPTY_SNAPSHOT_BINDING = {
    "resource_digests": {},
    "skill_digests": {},
    "guidance_digests": [],
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

    with pytest.raises(UnsupportedRunSchemaVersionError, match=UNSUPPORTED_RUN_SCHEMA_MESSAGE) as exc_info:
        store.load_run("run-20260101T000001-000001")
    assert exc_info.value.code == "unsupported_run_schema"


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
        validate_run_schema_version({"schema_version": "3"})
    with pytest.raises(UnsupportedRunSchemaVersionError):
        validate_run_schema_version({"schema_version": True})


def test_v3_run_rejects_legacy_config_digest(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    run_path = tmp_path / "run-20260101T000001-000001" / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["digests"]["config"] = payload["digests"].pop("config_contract")
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PersistenceError, match="digests.config is not supported"):
        store.load_run("run-20260101T000001-000001")


def test_v3_run_requires_split_config_digests(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    run_path = tmp_path / "run-20260101T000001-000001" / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    del payload["digests"]["config_execution"]
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PersistenceError, match="digests.config_execution is required"):
        store.load_run("run-20260101T000001-000001")


def test_schema_version_gate_still_requires_supported_binding_shape(tmp_path: Path) -> None:
    """Schema version alone is insufficient; legacy list bindings are rejected at load."""

    store = FileRunStore(tmp_path)
    _create_run(store)
    run_path = tmp_path / "run-20260101T000001-000001" / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["context_snapshot_binding"] = {
        "workspace": str(store.root),
        "resource_digests": [],
        "skill_digests": [],
    }
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Exception, match="Unsupported context snapshot binding|legacy|Recreate"):
        store.load_run("run-20260101T000001-000001")
