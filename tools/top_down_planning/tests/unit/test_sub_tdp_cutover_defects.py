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
    workspace_changes_from_output_evidence,
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
            "manifest_path": str(package.manifest_path),
            "units": [
                {
                    "plan_item_id": "item-a",
                    "child_run_id": child_id,
                    "unit_plan_digest": package.units["item-a"].plan_digest,
                    "status": "completed",
                    "accepted_result": tampered,
                    "accepted_result_digest": accepted_result_digest(tampered),
                }
            ],
        }
    }
    with pytest.raises(ValueError, match="live|does not match|attestation"):
        collect_parent_sub_tdp_authorized_workspace_changes(
            store,
            production=production,
            workspace=package.workspace_path,
        )


def test_parent_collect_requires_sub_tdps_manifest_path(tmp_path: Path) -> None:
    """Parent auth must load package initial snapshot from sub_tdps.manifest_path."""

    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    _, accepted = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )
    production = {
        "sub_tdps": {
            "units": [
                {
                    "plan_item_id": "item-a",
                    "child_run_id": child_id,
                    "unit_plan_digest": package.units["item-a"].plan_digest,
                    "status": "completed",
                    "accepted_result": accepted,
                    "accepted_result_digest": accepted_result_digest(accepted),
                }
            ],
        }
    }
    with pytest.raises(ValueError, match="manifest_path"):
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


def test_workspace_changes_from_evidence_uses_latest_per_path() -> None:
    """Accepted workspace_changes reflect final captured bytes, not first batch."""

    evidence = [
        {
            "ref": "shared/state.json",
            "sha256": "a" * 64,
            "size": 1,
            "snapshot_ref": "artifacts/first",
        },
        {
            "ref": "shared/state.json",
            "sha256": "b" * 64,
            "size": 2,
            "snapshot_ref": "artifacts/second",
        },
    ]
    changes = workspace_changes_from_output_evidence(evidence)
    assert changes["shared/state.json"]["sha256"] == "b" * 64
    assert changes["shared/state.json"]["size"] == 2


def test_topo_sort_cycle_raises() -> None:
    """Dependency cycles must fail closed, not merge in arbitrary order."""

    from top_down_planning.package.execution_validation import topo_sort_sub_tdp_items
    from top_down_planning.package.loader import ExecutionPackageError

    records = [
        {"plan_item_id": "a", "depends_on": ["b"]},
        {"plan_item_id": "b", "depends_on": ["a"]},
    ]
    with pytest.raises(ExecutionPackageError, match="cycle"):
        topo_sort_sub_tdp_items(
            records,
            item_id=lambda r: str(r["plan_item_id"]),
            depends_on_ids=lambda r: list(r.get("depends_on") or []),
        )


def test_verify_merged_baseline_rejects_workspace_tamper(tmp_path: Path) -> None:
    """Merged baseline map must reject bytes that diverge from accepted hashes."""

    from top_down_planning.package.execution_validation import (
        verify_merged_baseline_workspace_bytes,
    )

    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    wrapper, _ = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )
    shared = Path(package.workspace_path) / "shared" / "state.json"
    shared.write_text('{"tampered": true}\n', encoding="utf-8")
    expected_snapshot = str(
        (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
    )
    with pytest.raises(ExecutionPackageError, match="do not match accepted sha256"):
        verify_merged_baseline_workspace_bytes(
            [wrapper],
            workspace=Path(package.workspace_path),
            initial_snapshot_digest=expected_snapshot,
            resolved_config=package.resolved_config,
            unit_depends_on={
                uid: list(u.depends_on) for uid, u in package.units.items()
            },
        )


def test_agent_readme_documents_content_bound_accepted_result_fields() -> None:
    from top_down_planning.schema_docs import AGENT_README_TEXT

    assert "workspace_changes" in AGENT_README_TEXT
    assert "baseline_context_snapshot_digest" in AGENT_README_TEXT
    assert "final_context_snapshot_digest" in AGENT_README_TEXT


def test_accepted_child_two_batches_same_file_records_final_hash(tmp_path: Path) -> None:
    """One child may capture the same path twice; acceptance binds the latest hash."""

    from core_tools.persistence import digest_file
    from top_down_planning.agent_tool.artifacts import capture_output_artifact
    from top_down_planning.persistence.digests import compute_output_digest

    store, package = _build_package(tmp_path)
    shared = Path(package.workspace_path) / "shared" / "state.json"
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    shared.write_text('{"version": 3}\n', encoding="utf-8")
    capture_output_artifact(
        store,
        child_id,
        workspace=Path(package.workspace_path),
        ref="shared/state.json",
    )
    production = store.load_production(child_id)
    batch_id = str((production.get("batches") or [{}])[0].get("id") or "")
    evidence = list(production.get("output_evidence") or [])
    evidence.append(
        {
            "id": "out-a-v3",
            "type": "artifact",
            "ref": "shared/state.json",
            "sha256": digest_file(shared),
            "size": shared.stat().st_size,
            "media_type": "application/json",
            "captured_at": "2026-01-01T00:00:00Z",
            "snapshot_ref": "artifacts/manual-v3",
            "batch_id": batch_id,
        }
    )
    nested_v3 = {
        key: value
        for key, value in evidence[-1].items()
        if key != "batch_id"
    }
    batches = [dict(batch) for batch in production.get("batches") or []]
    if batches:
        result = dict(batches[0].get("result") or {})
        result["outputs"] = list(result.get("outputs") or []) + [nested_v3]
        contributions = list(result.get("contributions") or [])
        if contributions:
            contrib = dict(contributions[0])
            contrib["output_refs"] = list(contrib.get("output_refs") or []) + [
                "out-a-v3"
            ]
            contributions[0] = contrib
        result["contributions"] = contributions
        batches[0]["result"] = result
    expected_prod = int(production["revision"])
    production = dict(production)
    production["batches"] = batches
    production["output_evidence"] = evidence
    production["output_revision"] = int(production.get("output_revision") or 0) + 1
    production["revision"] = expected_prod + 1
    store.save_production(child_id, production, expected_prod)

    run = store.load_run(child_id)
    expected = int(run["revision"])
    run = dict(run)
    digests = dict(run.get("digests") or {})
    digests["output"] = compute_output_digest(production)
    run["digests"] = digests
    run["revision"] = expected + 1
    store.save_run(child_id, run, expected)

    _, accepted = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )
    entry = accepted["workspace_changes"]["shared/state.json"]
    assert entry["sha256"] == digest_file(shared)
