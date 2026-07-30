"""Unit tests for persistence store, digests, and atomic writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import (
    FileRunStore,
    PersistenceError,
    StoreRevisionConflictError,
    atomic_write_json,
    compute_config_digest,
    compute_plan_digest,
    digest_text,
)


def _sample_plan(revision: int = 0) -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
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

    run = store.create_run(
        "run-001",
        plan=plan,
        resolved_config=config,
        input_digest="input-a",
        output_goal_digest="goal-b",
    )

    run_dir = tmp_path / "run-001"
    assert run["revision"] == 0
    assert run["status"] == "running"
    assert run["digests"]["config"] == compute_config_digest(config)
    assert run["digests"]["plan"] == compute_plan_digest(plan)
    assert (run_dir / "resolved-config.yaml").exists()
    assert (run_dir / "run.json").exists()
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "production.json").exists()
    assert (run_dir / "reviews").is_dir()
    assert (run_dir / "events.jsonl").exists()

    loaded_plan = store.load_plan("run-001")
    assert loaded_plan["revision"] == 0
    assert loaded_plan["items"][0]["title"] == "Root"
    assert store.load_plan_model("run-001").output_goal == "Deliver the output."
    assert store.load_run("run-001")["digests"]["input"] == "input-a"


def test_load_resolved_config_round_trip(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    config = {"planning": {"max_depth": 5, "max_expansion_per_item": 3}}
    store.create_run(
        "run-001",
        plan=_sample_plan(),
        resolved_config=config,
        input_digest="input-a",
        output_goal_digest="goal-b",
    )

    assert store.load_resolved_config("run-001") == config


def test_create_run_requires_digests(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    with pytest.raises(PersistenceError, match="input_digest and output_goal_digest"):
        store.create_run(
            "run-001",
            plan=_sample_plan(),
            resolved_config={},
            input_digest="",
            output_goal_digest="goal-b",
        )


def test_save_plan_revision_conflict(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = _sample_plan()
    store.create_run(
        "run-001",
        plan=plan,
        resolved_config={},
        input_digest="input-a",
        output_goal_digest="goal-b",
    )

    updated = plan.to_dict()
    updated["revision"] = 1
    store.save_plan("run-001", updated, expected_revision=0)

    stale = plan.to_dict()
    stale["revision"] = 2
    with pytest.raises(StoreRevisionConflictError):
        store.save_plan("run-001", stale, expected_revision=0)


def test_save_plan_requires_explicit_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = _sample_plan()
    store.create_run(
        "run-001",
        plan=plan,
        resolved_config={},
        input_digest="input-a",
        output_goal_digest="goal-b",
    )

    payload = plan.to_dict()
    del payload["revision"]
    with pytest.raises(PersistenceError, match="explicit revision"):
        store.save_plan("run-001", payload, expected_revision=0)


def test_save_plan_model_round_trip(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = _sample_plan()
    store.create_run(
        "run-001",
        plan=plan,
        resolved_config={},
        input_digest="input-a",
        output_goal_digest="goal-b",
    )

    updated = _sample_plan(revision=1)
    store.save_plan_model("run-001", updated, expected_revision=0)
    assert store.load_plan_model("run-001").revision == 1


def test_reload_after_new_store_instance(tmp_path: Path) -> None:
    plan = _sample_plan()
    config = {"mode": "test"}

    store = FileRunStore(tmp_path)
    store.create_run(
        "run-001",
        plan=plan,
        resolved_config=config,
        input_digest="input-a",
        output_goal_digest="goal-b",
    )

    updated = plan.to_dict()
    updated["revision"] = 1
    store.save_plan("run-001", updated, expected_revision=0)

    reloaded = FileRunStore(tmp_path)
    assert reloaded.load_plan("run-001")["revision"] == 1
    assert reloaded.load_run("run-001")["revision"] == 0


def test_append_event_is_append_only(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    store.create_run(
        "run-001",
        plan=_sample_plan(),
        resolved_config={},
        input_digest="input-a",
        output_goal_digest="goal-b",
    )

    store.append_event("run-001", {"type": "phase_changed", "phase": "production"})
    store.append_event("run-001", {"type": "plan_updated", "revision": 1})

    events = store.load_events("run-001")
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
    store.create_run(
        "run-001",
        plan=_sample_plan(),
        resolved_config={},
        input_digest="input-a",
        output_goal_digest="goal-b",
    )
    with pytest.raises(PersistenceError, match="already exists"):
        store.create_run(
            "run-001",
            plan=_sample_plan(),
            resolved_config={},
            input_digest="input-a",
            output_goal_digest="goal-b",
        )
