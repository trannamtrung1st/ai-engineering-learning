"""Regression tests for Slice 3 round-10 review (TDP-PERSIST-036..038, TDP-PKG-001)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError, atomic_write_json, dump_yaml
from top_down_planning.config.context_digests import validate_resume_context_bindings
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from tests.helpers import create_run_kwargs, minimal_resolved_config
from tests.unit.test_commit_crash_recovery import _create_run


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0010{suffix}-0010{suffix}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_creating_run_symlink_does_not_delete_existing_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_b = _new_run_id("01")
    _create_run(store, run_b)
    run_b_bytes = (store.run_dir(run_b) / "run.json").read_bytes()

    run_a = _new_run_id("02")
    creating = tmp_path / f".creating-{run_a}"
    creating.symlink_to(store.run_dir(run_b), target_is_directory=True)

    workspace = store.root
    config = minimal_resolved_config()
    plan = Plan(
        id=f"plan-{run_a}",
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
    with pytest.raises(PersistenceError, match="must not be a symlink"):
        store.create_run(run_a, plan=plan, **create_run_kwargs(workspace, resolved_config=config))

    assert (store.run_dir(run_b) / "run.json").read_bytes() == run_b_bytes


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
@pytest.mark.parametrize(
    "filename",
    ["plan.json", "production.json", "resolved-config.yaml", "invocation.json"],
)
def test_canonical_snapshot_symlink_rejects_load(tmp_path: Path, filename: str) -> None:
    store = FileRunStore(tmp_path)
    run_a = _new_run_id("11")
    run_b = _new_run_id("12")
    _create_run(store, run_a)
    _create_run(store, run_b)

    target = store.run_dir(run_b) / filename
    link = store.run_dir(run_a) / filename
    if link.exists():
        link.unlink()
    link.symlink_to(target)

    loader = {
        "plan.json": store.load_plan,
        "production.json": store.load_production,
        "resolved-config.yaml": store.load_resolved_config,
        "invocation.json": store.load_invocation,
    }[filename]
    with pytest.raises(PersistenceError, match="must not be a symlink"):
        loader(run_a)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_review_record_symlink_rejects_load_without_mutating_run_json(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("21")
    _create_run(store, run_id)
    run_json = store.run_dir(run_id) / "run.json"
    before = run_json.read_bytes()
    review_link = store.reviews_dir(run_id) / "review-1.json"
    review_link.symlink_to(run_json)

    with pytest.raises(PersistenceError, match="must not be a symlink"):
        store.load_review(run_id, "review-1")

    assert run_json.read_bytes() == before


def test_create_run_rejects_mismatched_context_snapshot_binding(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("31")
    workspace = store.root
    config = minimal_resolved_config()
    kwargs = create_run_kwargs(workspace, resolved_config=config)
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
    kwargs = dict(kwargs)
    kwargs["context_snapshot_digest"] = "0" * 64

    with pytest.raises(PersistenceError, match="context_snapshot"):
        store.create_run(run_id, plan=plan, **kwargs)


def test_config_only_structural_context_change_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("41")
    _create_run(store, run_id)
    before = (store.run_dir(run_id) / "resolved-config.yaml").read_bytes()
    config = store.load_resolved_config(run_id)
    config = dict(config)
    agent_context = dict(config.get("agent_context") or {})
    roles = dict(agent_context.get("roles") or {})
    producer = dict(roles.get("producer") or {})
    producer["guidance"] = [{"text": "New inline guidance for structural drift."}]
    roles["producer"] = producer
    agent_context["roles"] = roles
    config["agent_context"] = agent_context

    with pytest.raises(PersistenceError, match="structural context change"):
        store.commit(run_id, CommitSpec(resolved_config=config))

    assert (store.run_dir(run_id) / "resolved-config.yaml").read_bytes() == before


def test_config_only_input_ref_change_remains_resumable(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("51")
    _create_run(store, run_id)
    config = store.load_resolved_config(run_id)
    config = dict(config)
    run_section = dict(config.get("run") or {})
    run_section["input_refs"] = ["README.md", "extra.txt"]
    config["run"] = run_section
    workspace = Path(str(store.load_run(run_id)["workspace"])).resolve()
    (workspace / "extra.txt").write_text("extra\n", encoding="utf-8")

    store.commit(run_id, CommitSpec(resolved_config=config))

    run = store.load_run(run_id)
    production = store.load_production(run_id)
    loaded_config = store.load_resolved_config(run_id)
    assert (
        validate_resume_context_bindings(
            run,
            production,
            loaded_config,
            workspace=workspace,
        )
        is None
    )


def test_load_production_rejects_coerced_evidence_size(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("61")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["output_evidence"] = [
        {
            "id": "ev-1",
            "type": "artifact",
            "ref": "out.txt",
            "sha256": "a" * 64,
            "size": True,
            "media_type": "text/plain",
            "captured_at": "2026-01-01T00:00:00Z",
        }
    ]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="size must be a non-negative integer"):
        store.load_production(run_id)


def test_build_packaging_wheelhouse_prints_path_only_to_stdout(tmp_path: Path) -> None:
    import importlib.util
    import io
    from contextlib import redirect_stdout

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "build_packaging_wheelhouse.py"
    spec = importlib.util.spec_from_file_location("build_packaging_wheelhouse", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination = tmp_path / "wheelhouse"

    with patch.object(
        module.subprocess,
        "run",
        return_value=subprocess.CompletedProcess([], 0),
    ):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            assert module.main([str(destination)]) == 0

    assert buffer.getvalue().strip() == str(destination.resolve())
