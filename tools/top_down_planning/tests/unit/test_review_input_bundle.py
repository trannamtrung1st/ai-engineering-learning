"""Durable review-input bundle persistence (file-backed reviewer snapshots)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore, PersistenceError
from top_down_planning.persistence.review_input_bundle import (
    materialize_review_input_bundle,
    review_attempt_id,
)
from tests.helpers import create_run_kwargs, make_review_loop


def _create_run(store: FileRunStore, run_id: str) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=1,
        output_goal="Deliver the feature.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(
            store.root,
            resolved_config={"run": {"output_goal": "Deliver the feature."}},
        ),
        phase=WHOLE_OUTPUT_REVIEW,
    )


def _package(*, evidence: str, digest: str = "a" * 64) -> dict:
    return {
        "run_id": "run-20260101T010101-010101",
        "phase": WHOLE_OUTPUT_REVIEW,
        "type": "whole_output",
        "loop_id": "review-whole-output-01",
        "purpose": "Mandatory whole-output review before final outcome",
        "scope": {"kind": "whole_output"},
        "target_revision": 1,
        "target_digest": digest,
        "stage": "initial_review",
        "protocol_instructions": "Submit decisions only through tdp agent review respond.",
        "tool_instructions": {"respond": "tdp agent review respond --run run-id"},
        "production": {"revision": 1, "output_revision": 1, "batches": []},
        "plan_contracts": {"item-root": {"title": "Root"}},
        "evidence_by_item": {"item-root": [{"evidence_id": "ev-1", "body": evidence}]},
        "analysis_context": {"notes": "context"},
        "agent_context": {"role": "reviewer"},
    }


def test_review_attempt_id_is_scoped_to_stage_revision_and_cycle() -> None:
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=2,
        revision_cycles=1,
        active_stage="finding_verification",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    assert review_attempt_id(loop) == "finding_verification-rev2-cycle1"


def test_review_attempt_id_includes_allocated_finding_set() -> None:
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
        finding_set_id="review-whole-output-01-fs-02",
    )
    assert review_attempt_id(loop) == (
        "initial_review-rev1-cycle0-review-whole-output-01-fs-02"
    )


def test_materialize_review_input_bundle_writes_manifest_and_hashed_inputs(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010101-010101"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())
    package = _package(evidence="small-evidence")

    bundle = materialize_review_input_bundle(
        store,
        run_id,
        loop=loop,
        review_package=package,
        workspace=tmp_path,
    )

    assert bundle.reused is False
    manifest_path = tmp_path / run_id / "review-inputs" / loop.id / bundle.attempt_id / "manifest.json"
    assert manifest_path.is_file()
    assert bundle.manifest_relpath == str(
        Path(run_id) / "review-inputs" / loop.id / bundle.attempt_id / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["review_type"] == "whole_output"
    assert manifest["stage"] == "initial_review"
    assert manifest["loop_id"] == loop.id
    assert manifest["run_id"] == run_id
    kinds = {entry["kind"]: entry for entry in manifest["inputs"]}
    assert kinds["production"]["required"] is True
    assert kinds["evidence"]["path"] == "evidence.json"
    bundle_dir = manifest_path.parent
    for entry in manifest["inputs"]:
        payload_path = bundle_dir / entry["path"]
        data = payload_path.read_bytes()
        assert entry["size_bytes"] == len(data)
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["required"] is True


def test_materialize_review_input_bundle_reuses_immutable_snapshot_for_same_attempt(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010102-010102"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())
    first = materialize_review_input_bundle(
        store,
        run_id,
        loop=loop,
        review_package=_package(evidence="original-evidence"),
        workspace=tmp_path,
    )
    original_hash = {
        entry["kind"]: entry["sha256"] for entry in first.manifest["inputs"]
    }

    second = materialize_review_input_bundle(
        store,
        run_id,
        loop=loop,
        review_package=_package(evidence="mutated-after-pause", digest="b" * 64),
        workspace=tmp_path,
    )

    assert second.reused is True
    assert second.attempt_id == first.attempt_id
    assert second.manifest["inputs"] == first.manifest["inputs"]
    evidence_path = first.manifest_path.parent / "evidence.json"
    assert b"original-evidence" in evidence_path.read_bytes()
    assert b"mutated-after-pause" not in evidence_path.read_bytes()
    reused_hash = {
        entry["kind"]: entry["sha256"] for entry in second.manifest["inputs"]
    }
    assert reused_hash == original_hash


def test_materialize_review_input_bundle_writes_new_snapshot_for_new_attempt(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010103-010103"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())
    first = materialize_review_input_bundle(
        store,
        run_id,
        loop=loop,
        review_package=_package(evidence="rev1-evidence"),
        workspace=tmp_path,
    )
    next_loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=2,
        revision_cycles=1,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    second = materialize_review_input_bundle(
        store,
        run_id,
        loop=next_loop,
        review_package=_package(evidence="rev2-evidence", digest="c" * 64),
        workspace=tmp_path,
    )

    assert second.reused is False
    assert second.attempt_id != first.attempt_id
    first_evidence = {
        entry["sha256"] for entry in first.manifest["inputs"] if entry["kind"] == "evidence"
    }
    second_evidence = {
        entry["sha256"] for entry in second.manifest["inputs"] if entry["kind"] == "evidence"
    }
    assert first_evidence != second_evidence
    assert b"rev2-evidence" in (second.manifest_path.parent / "evidence.json").read_bytes()


def test_review_input_bundle_omits_capability_secrets(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010104-010104"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())
    package = _package(evidence="ok")
    package["capability_token"] = "secret-token-value"
    package["production"]["capability_token"] = "nested-secret"

    bundle = materialize_review_input_bundle(
        store,
        run_id,
        loop=loop,
        review_package=package,
        workspace=tmp_path,
    )

    blob = b""
    for path in bundle.manifest_path.parent.rglob("*"):
        if path.is_file():
            blob += path.read_bytes()
    assert b"secret-token-value" not in blob
    assert b"nested-secret" not in blob


def test_review_input_bundle_rejects_symlink_escape(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010105-010105"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())
    outside = tmp_path / "outside"
    outside.mkdir()
    review_inputs = store.run_dir(run_id) / "review-inputs"
    review_inputs.symlink_to(outside)
    with pytest.raises(Exception, match="symlink"):
        materialize_review_input_bundle(
            store,
            run_id,
            loop=loop,
            review_package=_package(evidence="x"),
            workspace=tmp_path,
        )


def test_materialize_writes_new_bundle_when_finding_set_changes(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010106-010106"
    _create_run(store, run_id)
    first_loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
        finding_set_id="review-whole-output-01-fs-01",
    )
    store.save_review(run_id, first_loop.to_dict())
    first_package = _package(evidence="same-artifact")
    first_package["finding_set_id"] = "review-whole-output-01-fs-01"
    first = materialize_review_input_bundle(
        store,
        run_id,
        loop=first_loop,
        review_package=first_package,
        workspace=tmp_path,
    )

    next_loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
        finding_set_id="review-whole-output-01-fs-02",
    )
    next_package = _package(evidence="same-artifact")
    next_package["finding_set_id"] = "review-whole-output-01-fs-02"
    second = materialize_review_input_bundle(
        store,
        run_id,
        loop=next_loop,
        review_package=next_package,
        workspace=tmp_path,
    )

    assert second.reused is False
    assert second.attempt_id != first.attempt_id
    assert first.bootstrap_fields["finding_set_id"] == "review-whole-output-01-fs-01"
    assert second.bootstrap_fields["finding_set_id"] == "review-whole-output-01-fs-02"
    assert first.manifest_path.is_file()
    assert second.manifest_path.is_file()


def test_materialize_rejects_corrupt_snapshot_instead_of_reusing(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010107-010107"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())
    first = materialize_review_input_bundle(
        store,
        run_id,
        loop=loop,
        review_package=_package(evidence="original-evidence"),
        workspace=tmp_path,
    )
    evidence_path = first.manifest_path.parent / "evidence.json"
    evidence_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(PersistenceError, match="does not match the manifest"):
        materialize_review_input_bundle(
            store,
            run_id,
            loop=loop,
            review_package=_package(evidence="should-not-overwrite"),
            workspace=tmp_path,
        )
    assert b"original-evidence" not in evidence_path.read_bytes()
    assert b"should-not-overwrite" not in evidence_path.read_bytes()


def test_materialize_rejects_incomplete_bundle_directory(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010108-010108"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())
    dest = (
        tmp_path
        / run_id
        / "review-inputs"
        / loop.id
        / review_attempt_id(loop)
    )
    dest.mkdir(parents=True)
    (dest / "orphan.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(PersistenceError, match="manifest"):
        materialize_review_input_bundle(
            store,
            run_id,
            loop=loop,
            review_package=_package(evidence="x"),
            workspace=tmp_path,
        )


def test_materialize_uses_relative_path_when_store_is_outside_workspace(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    workspace = tmp_path / "project"
    workspace.mkdir()
    store = FileRunStore(runs_root)
    run_id = "run-20260101T010109-010109"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        revision_cycles=0,
        active_stage="initial_review",
        scope={"kind": "whole_output"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())

    bundle = materialize_review_input_bundle(
        store,
        run_id,
        loop=loop,
        review_package=_package(evidence="x"),
        workspace=workspace,
    )

    assert bundle.manifest_path.is_file()
    assert ".." in Path(bundle.manifest_relpath).parts
    assert bundle.manifest_relpath.endswith(
        f"{run_id}/review-inputs/{loop.id}/{bundle.attempt_id}/manifest.json"
    )
