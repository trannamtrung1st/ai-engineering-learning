"""Defect fixes for content-bound Sub-TDP cutover consistency."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.package.execution_validation import (
    merge_authorized_workspace_changes,
    verify_workspace_matches_authorized_changes,
)
from top_down_planning.package.lineage import (
    accepted_result_digest,
    verify_accepted_result_attestation,
    verify_accepted_result_matches_live_delivery,
)
from top_down_planning.package.loader import ExecutionPackageError
from top_down_planning.orchestrator.prepare_resume import (
    collect_parent_sub_tdp_authorized_workspace_changes,
)
from tests.unit.test_sub_tdp_content_bound_baseline import (
    _accepted_wrapper_for_shared,
    _build_package,
    _create_and_accept_shared_writer,
)


def test_merge_workspace_changes_rejects_delete_operation() -> None:
    """Hard cutover: delete ops rejected until tombstone capture exists."""

    first = {
        "path.json": {
            "operation": "write",
            "sha256": "a" * 64,
            "size": 1,
            "snapshot_ref": "artifacts/x",
        }
    }
    second = {
        "path.json": {
            "operation": "delete",
            "prior_sha256": "a" * 64,
        }
    }
    with pytest.raises(ExecutionPackageError, match="delete"):
        merge_authorized_workspace_changes(first, second)


def test_verify_workspace_rejects_delete_operation(tmp_path: Path) -> None:
    authorized = {
        "gone.json": {
            "operation": "delete",
            "prior_sha256": "a" * 64,
        }
    }
    with pytest.raises(ExecutionPackageError, match="delete"):
        verify_workspace_matches_authorized_changes(
            ["gone.json"],
            authorized_changes=authorized,
            workspace=tmp_path,
        )


def test_attestation_rejects_output_refs_without_matching_workspace_changes() -> None:
    """output_refs resource paths must appear in workspace_changes."""

    unit = {
        "plan_item_id": "item-a",
        "child_run_id": "run-child",
        "unit_plan_digest": "p" * 64,
        "accepted_result": {
            "schema_version": 1,
            "package_id": "pkg",
            "package_digest": "d" * 64,
            "unit_id": "item-a",
            "unit_plan_digest": "p" * 64,
            "assigned_subtree_digest": "s" * 64,
            "child_run_id": "run-child",
            "output_revision": 1,
            "output_digest": "o" * 64,
            "whole_output_review_id": "review-1",
            "whole_output_review_digest": "r" * 64,
            "outcome": "accepted",
            "evidence_digest": "e" * 64,
            "output_refs": [
                {"id": "out-a", "type": "artifact", "ref": "shared/state.json"}
            ],
            "contributions": [],
            "workspace_changes": {},
            "baseline_context_snapshot_digest": "b" * 64,
            "final_context_snapshot_digest": "f" * 64,
            "completion_assessment": "done",
        },
    }
    unit["accepted_result_digest"] = accepted_result_digest(unit["accepted_result"])
    with pytest.raises(ValueError, match="workspace_changes"):
        verify_accepted_result_attestation(unit)


def test_attestation_rejects_string_output_refs() -> None:
    """Hard cutover: output_refs must be objects with ref, not bare strings."""

    unit = {
        "plan_item_id": "item-a",
        "child_run_id": "run-child",
        "unit_plan_digest": "p" * 64,
        "accepted_result": {
            "schema_version": 1,
            "package_id": "pkg",
            "package_digest": "d" * 64,
            "unit_id": "item-a",
            "unit_plan_digest": "p" * 64,
            "assigned_subtree_digest": "s" * 64,
            "child_run_id": "run-child",
            "output_revision": 1,
            "output_digest": "o" * 64,
            "whole_output_review_id": "review-1",
            "whole_output_review_digest": "r" * 64,
            "outcome": "accepted",
            "evidence_digest": "e" * 64,
            "output_refs": ["out-a"],
            "contributions": [],
            "workspace_changes": {},
            "baseline_context_snapshot_digest": "b" * 64,
            "final_context_snapshot_digest": "f" * 64,
            "completion_assessment": "done",
        },
    }
    unit["accepted_result_digest"] = accepted_result_digest(unit["accepted_result"])
    with pytest.raises(ValueError, match="output_refs"):
        verify_accepted_result_attestation(unit)


def test_attestation_rejects_delete_operation_until_capture_exists() -> None:
    """Delete tombstones are not producible yet — reject incomplete records."""

    unit = {
        "plan_item_id": "item-a",
        "child_run_id": "run-child",
        "unit_plan_digest": "p" * 64,
        "accepted_result": {
            "schema_version": 1,
            "package_id": "pkg",
            "package_digest": "d" * 64,
            "unit_id": "item-a",
            "unit_plan_digest": "p" * 64,
            "assigned_subtree_digest": "s" * 64,
            "child_run_id": "run-child",
            "output_revision": 1,
            "output_digest": "o" * 64,
            "whole_output_review_id": "review-1",
            "whole_output_review_digest": "r" * 64,
            "outcome": "accepted",
            "evidence_digest": "e" * 64,
            "output_refs": [],
            "contributions": [],
            "workspace_changes": {
                "gone.json": {"operation": "delete", "prior_sha256": "a" * 64}
            },
            "baseline_context_snapshot_digest": "b" * 64,
            "final_context_snapshot_digest": "f" * 64,
            "completion_assessment": "done",
        },
    }
    unit["accepted_result_digest"] = accepted_result_digest(unit["accepted_result"])
    with pytest.raises(ValueError, match="delete"):
        verify_accepted_result_attestation(unit)


def test_live_match_rejects_tampered_workspace_changes(tmp_path: Path) -> None:
    """Stored accepted_result must re-derive from live child delivery."""

    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    _, accepted = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )
    tampered = dict(accepted)
    changes = dict(tampered["workspace_changes"])
    path = next(iter(changes))
    entry = dict(changes[path])
    entry["sha256"] = "0" * 64
    changes[path] = entry
    tampered["workspace_changes"] = changes
    unit = {
        "plan_item_id": "item-a",
        "child_run_id": child_id,
        "unit_plan_digest": package.units["item-a"].plan_digest,
        "accepted_result": tampered,
        "accepted_result_digest": accepted_result_digest(tampered),
    }
    with pytest.raises(ValueError, match="live|does not match"):
        verify_accepted_result_matches_live_delivery(
            unit,
            child_run=store.load_run(child_id),
            child_production=store.load_production(child_id),
        )


def test_parent_collect_rejects_tampered_stored_workspace_changes(
    tmp_path: Path,
) -> None:
    """Parent auth must not trust stored workspace_changes without live match."""

    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    _, accepted = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )
    tampered = dict(accepted)
    changes = dict(tampered["workspace_changes"])
    path = next(iter(changes))
    entry = dict(changes[path])
    entry["sha256"] = "0" * 64
    changes[path] = entry
    tampered["workspace_changes"] = changes
    production = {
        "sub_tdps": {
            "units": [
                {
                    "plan_item_id": "item-a",
                    "child_run_id": child_id,
                    "unit_plan_digest": package.units["item-a"].plan_digest,
                    "status": "completed",
                    "accepted_result": tampered,
                    "accepted_result_digest": accepted_result_digest(tampered),
                }
            ]
        }
    }
    with pytest.raises(ValueError, match="live|does not match|attestation"):
        collect_parent_sub_tdp_authorized_workspace_changes(
            store,
            production=production,
            workspace=package.workspace_path,
        )


def test_factory_rejects_upstream_wrapper_that_does_not_match_live(
    tmp_path: Path,
) -> None:
    """Child create must live-validate upstream accepted_result attestations."""

    from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory

    store, package = _build_package(tmp_path)
    child_a = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    wrapper, accepted = _accepted_wrapper_for_shared(
        store, package, child_a, unit_id="item-a"
    )
    forged = dict(accepted)
    forged["final_context_snapshot_digest"] = "0" * 64
    forged_wrapper = {
        "accepted_result": forged,
        "accepted_result_digest": accepted_result_digest(forged),
        "upstream_contract_digest": wrapper["upstream_contract_digest"],
    }
    unit_b = package.units["item-b"]
    with pytest.raises(ExecutionPackageError, match="live|does not match|delivery"):
        PreparedRunFactory().create_child_run(
            store,
            package,
            unit_b,
            resolved_config=package.resolved_config,
            invocation={"command": "execute", "sub_tdp": {"unit_id": "item-b"}},
            upstream_accepted_results=[forged_wrapper],
            workspace_baseline_results=[forged_wrapper],
        )


def test_live_match_rejects_identity_fields_that_disagree_with_child_binding(
    tmp_path: Path,
) -> None:
    """Live match must re-derive from child package_binding, not stored identity."""

    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    _, accepted = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )
    tampered = dict(accepted)
    tampered["package_digest"] = "0" * 64
    unit = {
        "plan_item_id": "item-a",
        "child_run_id": child_id,
        "unit_plan_digest": package.units["item-a"].plan_digest,
        "accepted_result": tampered,
        "accepted_result_digest": accepted_result_digest(tampered),
    }
    with pytest.raises(ValueError, match="package_digest|live|does not match|binding"):
        verify_accepted_result_matches_live_delivery(
            unit,
            child_run=store.load_run(child_id),
            child_production=store.load_production(child_id),
        )


def test_agent_readme_documents_content_bound_accepted_result_fields() -> None:
    from top_down_planning.schema_docs import AGENT_README_TEXT

    assert "workspace_changes" in AGENT_README_TEXT
    assert "baseline_context_snapshot_digest" in AGENT_README_TEXT
    assert "final_context_snapshot_digest" in AGENT_README_TEXT
