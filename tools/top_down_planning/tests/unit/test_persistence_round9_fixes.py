"""Regression tests for Slice 3 round-9 review (TDP-PERSIST-032..035)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError, atomic_write_json
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.capabilities import (
    clear_capability_token_file,
    write_capability_token_file,
)
from top_down_planning.persistence.commit import CommitSpec
from tests.helpers import create_run_kwargs
from tests.support.persistence import _create_run


def _outside_file(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("outside\n", encoding="utf-8")
    return target


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_artifact_symlink_snapshot_rejects_cross_run_write(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_a = "run-20260101T000901-000901"
    run_b = "run-20260101T000902-000902"
    _create_run(store, run_a)
    _create_run(store, run_b)
    target_dir = store.artifacts_dir(run_b) / "target-snap"
    target_dir.mkdir(parents=True)
    snap_link = store.artifacts_dir(run_a) / "evil-snap"
    snap_link.symlink_to(target_dir, target_is_directory=True)

    with pytest.raises(PersistenceError, match="escapes run directory|must not be a symlink"):
        store.write_artifact_bytes(run_a, "evil-snap", "payload.bin", b"x")

    assert not (target_dir / "payload.bin").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_capability_token_symlink_rejects_outside_write(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    outside = _outside_file(tmp_path)
    capability_link = store.run_dir(run_id) / "capability"
    capability_link.symlink_to(outside.parent, target_is_directory=True)

    with pytest.raises(PersistenceError, match="must not be a symlink|escapes run directory"):
        write_capability_token_file(store, run_id, "cap-test.secret")

    assert outside.read_text(encoding="utf-8") == "outside\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_clear_capability_token_does_not_unlink_outside_target(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    outside = _outside_file(tmp_path)
    capability_link = store.run_dir(run_id) / "capability"
    capability_link.symlink_to(outside.parent, target_is_directory=True)
    token_path = outside.parent / "current"
    token_path.write_text("cap-1.secret\n", encoding="utf-8")

    with pytest.raises(PersistenceError, match="must not be a symlink|escapes run directory"):
        clear_capability_token_file(store, run_id)

    assert token_path.is_file()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_lexical_run_dir_symlink_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_a = "run-20260101T000901-000901"
    run_b = "run-20260101T000902-000902"
    _create_run(store, run_b)
    alias = tmp_path / run_a
    alias.symlink_to(tmp_path / run_b)

    with pytest.raises(PersistenceError, match="must not be a symlink"):
        store.run_dir(run_a)


def test_save_run_rejects_forged_plan_digest(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    before_bytes = (store.run_dir(run_id) / "run.json").read_bytes()
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    digests = dict(run.get("digests") or {})
    digests["plan"] = "0" * 64
    run["digests"] = digests

    with pytest.raises(PersistenceError, match="digests.plan"):
        store.save_run(run_id, run, expected)

    assert (store.run_dir(run_id) / "run.json").read_bytes() == before_bytes


def test_config_only_commit_updates_input_digest(tmp_path: Path) -> None:
    from top_down_planning.config import compute_input_digest

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    config = store.load_resolved_config(run_id)
    config = dict(config)
    run_section = dict(config.get("run") or {})
    run_section["input_refs"] = ["README.md", "extra.txt"]
    config["run"] = run_section
    workspace = Path(str(store.load_run(run_id)["workspace"])).resolve()
    (workspace / "extra.txt").write_text("extra input\n", encoding="utf-8")

    store.commit(run_id, CommitSpec(resolved_config=config))

    run = store.load_run(run_id)
    assert run["digests"]["input"] == compute_input_digest(config, base_dir=workspace)
    assert store.load_resolved_config(run_id)["run"]["input_refs"] == [
        "README.md",
        "extra.txt",
    ]


def test_save_run_rejects_illegal_completed_lifecycle(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    before_bytes = (store.run_dir(run_id) / "run.json").read_bytes()
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["outcome"] = None
    run["stop"] = None

    with pytest.raises(PersistenceError, match="completed run requires"):
        store.save_run(run_id, run, expected)

    assert (store.run_dir(run_id) / "run.json").read_bytes() == before_bytes
    assert store.load_run(run_id)["status"] == "running"


def test_create_run_rejects_malformed_initial_production(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
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
            )
        },
    )
    with pytest.raises(PersistenceError, match="production.batches"):
        store.create_run(
            run_id,
            plan=plan,
            production={"revision": 0, "output_revision": 0, "dispositions": {}},
            **create_run_kwargs(store.root),
        )

    assert not store.run_dir(run_id).exists()


def test_load_production_rejects_malformed_output_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production = dict(production)
    production["output_evidence"] = [{"id": "ev-1", "ref": "out.txt"}]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="output evidence|output_evidence"):
        store.load_production(run_id)
