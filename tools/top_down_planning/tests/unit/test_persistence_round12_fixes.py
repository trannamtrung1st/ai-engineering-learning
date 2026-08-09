"""Regression tests for Slice 3 round-12 review (TDP-PERSIST-044..047)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError, atomic_write_json
from top_down_planning.config import resolve_config, recompute_context_snapshot_binding
from top_down_planning.config.context_digests import sync_run_production_digests
from top_down_planning.domain.dispositions import TERMINAL_DISPOSITIONS
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.helpers import apply_production, create_run_kwargs, whole_plan_approval_record, write_config
from tests.unit.test_commit_crash_recovery import _create_run


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0031{suffix}-0031{suffix}"


def _create_resource_run(store: FileRunStore, run_id: str, workspace: Path) -> None:
    config = resolve_config(
        write_config(
            workspace / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - src/
""",
        ),
        cwd=workspace,
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="0000000001",
                title="Work",
                kind="work",
                planning_status="open",
            ),
        },
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(workspace, resolved_config=config),
    )


def test_save_run_rejects_authentic_unauthorized_context_snapshot_rebase(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    (src / "feature.py").write_text("v1\n", encoding="utf-8")
    store = FileRunStore(tmp_path / "runs")
    run_id = _new_run_id("01")
    _create_resource_run(store, run_id, workspace)

    (src / "feature.py").write_text("v2-unauthorized\n", encoding="utf-8")
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    expected = int(run["revision"])
    new_binding, new_digest = recompute_context_snapshot_binding(
        config,
        workspace=workspace,
    )
    run = dict(run)
    run["revision"] = expected + 1
    run["context_snapshot_binding"] = new_binding
    digests = dict(run.get("digests") or {})
    digests["context_snapshot"] = new_digest
    run["digests"] = digests
    before = (store.run_dir(run_id) / "run.json").read_bytes()

    with pytest.raises(PersistenceError, match="src/feature.py"):
        store.save_run(run_id, run, expected)

    assert (store.run_dir(run_id) / "run.json").read_bytes() == before


def test_save_run_rejects_workspace_identity_change(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("02")
    _create_run(store, run_id)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["workspace"] = str(tmp_path / "other-workspace")
    before = (store.run_dir(run_id) / "run.json").read_bytes()

    with pytest.raises(PersistenceError, match="run.workspace"):
        store.save_run(run_id, run, expected)

    assert (store.run_dir(run_id) / "run.json").read_bytes() == before


def test_sync_run_production_digests_still_rebases_authorized_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    module.write_text("v1\n", encoding="utf-8")
    store = FileRunStore(tmp_path / "runs")
    run_id = _new_run_id("03")
    _create_resource_run(store, run_id, workspace)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    pre_snapshot = store.load_run(run_id)["digests"]["context_snapshot"]
    module.write_text("v2\n", encoding="utf-8")
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    run["status"] = "running"
    run["outcome"] = None
    store.save_run(run_id, run, expected)
    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-work"],
            "dispositions": {
                "item-work": {
                    "disposition": "completed",
                    "evidence": "updated feature",
                },
            },
            "outputs": [{"id": "out-1", "type": "artifact", "ref": "src/feature.py"}],
            "contributions": [
                {
                    "item_id": "item-work",
                    "output_refs": ["out-1"],
                    "summary": "batch",
                },
            ],
            "summary": "production batch",
        },
        handler="apply",
        phase="production",
    )()

    assert sync_run_production_digests(store, run_id) is True
    post_snapshot = store.load_run(run_id)["digests"]["context_snapshot"]
    assert post_snapshot != pre_snapshot


def test_save_production_rejects_unknown_flat_disposition(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("11")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["dispositions"] = {"item-root": "garbage"}
    before = (store.run_dir(run_id) / "production.json").read_bytes()

    with pytest.raises(PersistenceError, match="terminal disposition"):
        store.save_production(run_id, production, expected)

    assert (store.run_dir(run_id) / "production.json").read_bytes() == before


def test_load_production_rejects_unknown_flat_disposition(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("12")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["dispositions"] = {"item-root": "garbage"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="terminal disposition"):
        store.load_production(run_id)


@pytest.mark.parametrize("disposition", sorted(TERMINAL_DISPOSITIONS))
def test_save_production_accepts_valid_terminal_dispositions(
    tmp_path: Path,
    disposition: str,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("13")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["dispositions"] = {"item-root": disposition}
    if disposition == "not_applicable":
        production["dispositions"] = {
            "item-root": {"disposition": disposition, "reason": "out of scope"},
        }
    elif disposition == "superseded":
        production["dispositions"] = {
            "item-root": {
                "disposition": disposition,
                "replacement_ref": "item-other",
            },
        }
    elif disposition == "blocked":
        production["dispositions"] = {
            "item-root": {"disposition": disposition, "evidence": "blocked"},
        }

    store.save_production(run_id, production, expected)
    loaded = store.load_production(run_id)
    value = loaded["dispositions"]["item-root"]
    if isinstance(value, dict):
        assert value["disposition"] == disposition
    else:
        assert value == disposition


def test_unknown_flat_disposition_blocks_load_before_readiness(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("14")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["dispositions"] = {"item-root": "garbage"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="terminal disposition"):
        store.load_production(run_id)


def test_load_run_rejects_integer_plan_digest(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("21")
    _create_run(store, run_id)
    run = store.load_run(run_id)
    digests = dict(run.get("digests") or {})
    digests["plan"] = int("0" * 64)
    run = dict(run)
    run["digests"] = digests
    atomic_write_json(store.run_dir(run_id) / "run.json", run)

    with pytest.raises(PersistenceError, match="digests.plan must be a string"):
        store.load_run(run_id)


def test_load_run_rejects_boolean_context_snapshot_digest(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("22")
    _create_run(store, run_id)
    run = store.load_run(run_id)
    digests = dict(run.get("digests") or {})
    digests["context_snapshot"] = True
    run = dict(run)
    run["digests"] = digests
    atomic_write_json(store.run_dir(run_id) / "run.json", run)

    with pytest.raises(PersistenceError, match="digests.context_snapshot must be a string"):
        store.load_run(run_id)


def test_load_production_rejects_numeric_disposition_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("31")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["dispositions"] = {
        "item-root": {"disposition": "blocked", "evidence": 42},
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="evidence must be a string"):
        store.load_production(run_id)


def test_load_production_rejects_numeric_not_applicable_reason(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("32")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["dispositions"] = {
        "item-root": {"disposition": "not_applicable", "reason": 1},
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="reason must be a string"):
        store.load_production(run_id)


def test_load_production_rejects_non_object_amendment_request(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("33")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["amendment_requests"] = ["not-an-object"]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="amendment_requests\\[0\\]"):
        store.load_production(run_id)


def test_load_production_rejects_malformed_completion_claim_goal_met(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("34")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["completion_claim"] = {
        "goal_met": "true",
        "goal_assessment": "Goal met.",
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="goal_met must be a boolean"):
        store.load_production(run_id)


def test_load_production_rejects_malformed_sub_tdp_unit_record(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("35")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["sub_tdps"] = {
        "version": 2,
        "status": "preparing",
        "active_unit_id": None,
        "units": [{"id": 1, "plan_item_id": "item-work", "status": "pending"}],
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="sub_tdps.units\\[0\\].id"):
        store.load_production(run_id)
