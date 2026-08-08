"""Unit tests for persistence store, digests, and atomic writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_tools.persistence import atomic_write_json, digest_text
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import (
    CURRENT_RUN_SCHEMA_VERSION,
    FileRunStore,
    PersistenceError,
    StoreRevisionConflictError,
    UNSUPPORTED_RUN_SCHEMA_MESSAGE,
    UnsupportedRunSchemaVersionError,
    validate_run_schema_version,
)
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
    compute_plan_digest,
)
from tests.helpers import create_run_kwargs, minimal_invocation, minimal_resolved_config

_EMPTY_SNAPSHOT_BINDING = {
    "resource_digests": {},
    "skill_digests": {},
    "guidance_digests": [],
}


def _create_run_kwargs(
    store: FileRunStore,
    *,
    resolved_config: dict | None = None,
) -> dict:
    config = minimal_resolved_config(**(resolved_config or {}))
    return create_run_kwargs(store.root, resolved_config=config)


def _seed_run(
    store: FileRunStore,
    run_id: str = "run-20260101T000001-000001",
    *,
    plan: Plan | None = None,
    resolved_config: dict | None = None,
    invocation: dict | None = None,
) -> dict:
    kwargs = _create_run_kwargs(store, resolved_config=resolved_config)
    if invocation is not None:
        kwargs = dict(kwargs)
        kwargs["invocation"] = invocation
    return store.create_run(run_id, plan=plan or _sample_plan(), **kwargs)


def _sample_plan(revision: int = 0) -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    return Plan(
        id="plan-001",
        revision=revision,
        output_goal="Deliver the output.",
        items={"item-root": root},
    )


def test_create_run_writes_expected_layout(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = _sample_plan()
    config = {"limits": {"planning": {"max_agent_turns": 5}}}
    kwargs = _create_run_kwargs(store, resolved_config=config)
    resolved = kwargs["resolved_config"]

    run = store.create_run("run-20260101T000001-000001", plan=plan, **kwargs)

    run_dir = tmp_path / "run-20260101T000001-000001"
    assert run["revision"] == 0
    assert run["status"] == "running"
    assert run["workspace"] == str(store.root)
    assert run["digests"]["config_contract"] == compute_config_contract_digest(resolved)
    assert run["digests"]["config_execution"] == compute_config_execution_digest(resolved)
    assert "config" not in run["digests"]
    assert run["digests"]["plan"] == compute_plan_digest(plan)
    assert (run_dir / "resolved-config.yaml").exists()
    assert (run_dir / "run.json").exists()
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "production.json").exists()
    assert (run_dir / "reviews").is_dir()
    assert (run_dir / "agent-requests").is_dir()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "invocation.json").exists()

    loaded_plan = store.load_plan("run-20260101T000001-000001")
    assert loaded_plan["revision"] == 0
    assert loaded_plan["items"][0]["title"] == "Root"
    assert loaded_plan["items"][0]["depth"] == 0
    assert store.load_plan_model("run-20260101T000001-000001").output_goal == "Deliver the output."
    assert store.load_run("run-20260101T000001-000001")["digests"]["input"] == kwargs["input_digest"]


def test_load_resolved_config_round_trip(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    overrides = {"planning": {"max_depth": 5, "max_expansion_per_item": 3}}
    expected = minimal_resolved_config(**overrides)
    expected["project"]["workspace"] = str(store.root.resolve())
    _seed_run(store, resolved_config=overrides)

    assert store.load_resolved_config("run-20260101T000001-000001") == expected


def test_create_run_persists_invocation_metadata(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    invocation = {
        "observability": {"log_level": "verbose", "agent_transcript": True},
        "runs_dir": {"path": str(tmp_path), "source": "config"},
        "command": "run",
    }
    _seed_run(
        store,
        resolved_config={"run": {"output_goal": "Goal."}},
        invocation=invocation,
    )
    assert store.load_invocation("run-20260101T000001-000001") == invocation
    store.save_invocation("run-20260101T000001-000001", {"command": "resume", "observability": {"log_level": "quiet"}})
    updated = store.load_invocation("run-20260101T000001-000001")
    assert updated["command"] == "resume"


def test_create_run_requires_digests(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    with pytest.raises(PersistenceError, match="context_spec_digest are required"):
        store.create_run(
            "run-20260101T000001-000001",
            plan=_sample_plan(),
            resolved_config={},
            input_digest="",
            output_goal_digest="goal-b",
            context_spec_digest="0" * 64,
            context_snapshot_digest="1" * 64,
            context_snapshot_binding=dict(_EMPTY_SNAPSHOT_BINDING),
            workspace=str(store.root),
            invocation=minimal_invocation(store.root),
        )


def test_create_run_requires_invocation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    kwargs = _create_run_kwargs(store)
    with pytest.raises(PersistenceError, match="invocation metadata is required"):
        store.create_run(
            "run-20260101T000001-000001",
            plan=_sample_plan(),
            **{**kwargs, "invocation": None},
        )


def test_create_run_requires_workspace(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    kwargs = _create_run_kwargs(store)
    with pytest.raises(PersistenceError, match="workspace is required"):
        store.create_run(
            "run-20260101T000001-000001",
            plan=_sample_plan(),
            **{**kwargs, "workspace": ""},
        )


def test_save_plan_revision_conflict(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = _sample_plan()
    _seed_run(store, plan=plan)

    updated = plan.to_dict()
    updated["revision"] = 1
    store.save_plan("run-20260101T000001-000001", updated, expected_revision=0)

    stale = plan.to_dict()
    stale["revision"] = 2
    with pytest.raises(StoreRevisionConflictError):
        store.save_plan("run-20260101T000001-000001", stale, expected_revision=0)


def test_save_plan_requires_explicit_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = _sample_plan()
    _seed_run(store, plan=plan)

    payload = plan.to_dict()
    del payload["revision"]
    with pytest.raises(PersistenceError, match="explicit revision"):
        store.save_plan("run-20260101T000001-000001", payload, expected_revision=0)


def test_save_plan_model_round_trip(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = _sample_plan()
    _seed_run(store, plan=plan)

    updated = _sample_plan(revision=1)
    store.save_plan_model("run-20260101T000001-000001", updated, expected_revision=0)
    assert store.load_plan_model("run-20260101T000001-000001").revision == 1


def test_reload_after_new_store_instance(tmp_path: Path) -> None:
    plan = _sample_plan()
    config = {"limits": {"planning": {"max_agent_turns": 5}}, "mode": "test"}

    store = FileRunStore(tmp_path)
    _seed_run(store, plan=plan, resolved_config=config)

    updated = plan.to_dict()
    updated["revision"] = 1
    store.save_plan("run-20260101T000001-000001", updated, expected_revision=0)

    reloaded = FileRunStore(tmp_path)
    assert reloaded.load_plan("run-20260101T000001-000001")["revision"] == 1
    assert reloaded.load_run("run-20260101T000001-000001")["revision"] == 1


def test_append_event_is_append_only(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _seed_run(store)

    store.append_event("run-20260101T000001-000001", {"type": "phase_changed", "phase": "production"})
    store.append_event("run-20260101T000001-000001", {"type": "plan_updated", "revision": 1})

    events = store.load_events("run-20260101T000001-000001")
    assert len(events) == 3
    assert events[0]["type"] == "run_created"
    assert events[1]["type"] == "phase_changed"
    assert events[2]["type"] == "plan_updated"
    assert "ts" in events[2]


def test_atomic_write_leaves_readable_primary_file_on_failed_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "plan.json"
    atomic_write_json(target, {"revision": 0, "ok": True})

    original_replace = Path.replace

    def flaky_replace(self: Path, other: Path) -> Path:
        if self.name.startswith(".plan.json.tmp-"):
            raise OSError("simulated crash during replace")
        return original_replace(self, other)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    with pytest.raises(OSError):
        atomic_write_json(target, {"revision": 1, "ok": False})

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["revision"] == 0
    assert payload["ok"] is True


def test_digest_helpers_are_stable() -> None:
    plan = _sample_plan()
    first = compute_plan_digest(plan)
    second = compute_plan_digest(plan.to_dict())
    assert first == second
    assert len(first) == 64
    assert digest_text("hello") == digest_text("hello")


def test_create_run_rejects_duplicate(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _seed_run(store)
    with pytest.raises(PersistenceError, match="already exists"):
        _seed_run(store)
