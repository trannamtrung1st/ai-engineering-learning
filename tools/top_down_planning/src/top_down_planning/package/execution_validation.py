"""Validate execution-time config and authoritative inputs against the package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from core_tools.persistence import digest_file

from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.config.binding_validation import validate_context_snapshot_binding
from top_down_planning.config.context import (
    compute_context_snapshot_digest_from_payload,
    compute_context_spec_digest_from_config,
)
from top_down_planning.config.context_digests import (
    build_initial_context_snapshot_binding_with_diagnostics,
    diff_snapshot_binding_paths,
    recompute_context_snapshot_binding_with_diagnostics,
    split_unauthorized_snapshot_paths,
)
from top_down_planning.package.loader import ExecutionPackageError, LoadedExecutionPackage
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
)


def validate_resolved_config_against_package(
    resolved: dict[str, Any],
    package: LoadedExecutionPackage,
    *,
    workspace: Path,
) -> None:
    """Reject semantic config drift before creating prepared execution runs."""

    context = package.manifest.get("context")
    if not isinstance(context, dict):
        raise ExecutionPackageError(
            "package context block missing",
            code="package_context_missing",
        )

    checks: list[tuple[str, str, str]] = [
        (
            "config_contract",
            compute_config_contract_digest(resolved),
            str(context.get("config_contract_digest") or ""),
        ),
        (
            "config_execution",
            compute_config_execution_digest(resolved),
            str(context.get("config_execution_digest") or ""),
        ),
        (
            "output_goal",
            compute_output_goal_digest(resolved, base_dir=workspace),
            str(context.get("output_goal_digest") or ""),
        ),
        (
            "context_spec",
            compute_context_spec_digest_from_config(resolved, workspace=workspace),
            str(context.get("context_spec_digest") or ""),
        ),
        (
            "input",
            compute_input_digest(resolved, base_dir=workspace),
            _aggregate_input_digest(context),
        ),
    ]
    for field, actual, expected in checks:
        if not expected:
            raise ExecutionPackageError(
                f"prepared package missing required {field} digest",
                code="package_context_incomplete",
            )
        if actual != expected:
            raise ExecutionPackageError(
                f"prepared package {field} digest mismatch: execution config drifted "
                "from the approved planning package",
                code="package_context_drift",
            )


def _load_package_snapshot_binding(package: LoadedExecutionPackage) -> dict[str, Any]:
    context = package.manifest.get("context")
    if not isinstance(context, dict):
        raise ExecutionPackageError(
            "package context block missing",
            code="package_context_missing",
        )
    binding_rel = str(context.get("context_snapshot_binding_file") or "").strip()
    if not binding_rel:
        raise ExecutionPackageError(
            "prepared package missing context_snapshot_binding_file",
            code="package_context_incomplete",
        )
    binding_path = (package.manifest_path.parent / binding_rel).resolve()
    package_root = package.manifest_path.parent.resolve()
    try:
        binding_path.relative_to(package_root)
    except ValueError as exc:
        raise ExecutionPackageError(
            f"context_snapshot_binding_file escapes package: {binding_rel}",
            code="package_path_escape",
        ) from exc
    if not binding_path.is_file():
        raise ExecutionPackageError(
            f"context_snapshot_binding file missing: {binding_rel}",
            code="package_context_incomplete",
        )
    try:
        stored_binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionPackageError(
            f"context_snapshot_binding file unreadable: {binding_rel}",
            code="package_context_incomplete",
        ) from exc
    validate_context_snapshot_binding(stored_binding)
    expected_snapshot = str(context.get("context_snapshot_digest") or "")
    stored_digest = compute_context_snapshot_digest_from_payload(stored_binding)
    if expected_snapshot and stored_digest != expected_snapshot:
        raise ExecutionPackageError(
            f"context_snapshot_binding digest mismatch: expected {expected_snapshot}, "
            f"got {stored_digest}",
            code="package_context_drift",
        )
    return stored_binding


def verify_package_immutable_contract(package: LoadedExecutionPackage) -> None:
    """Verify authoritative inputs and config contract — not live context snapshot."""

    workspace = package.workspace_path
    context = package.manifest.get("context")
    if not isinstance(context, dict):
        raise ExecutionPackageError(
            "package context block missing",
            code="package_context_missing",
        )

    input_block = context.get("input_refs")
    if not isinstance(input_block, dict):
        raise ExecutionPackageError(
            "package context.input_refs must be an object with aggregate_digest and refs",
            code="package_input_refs_invalid",
        )
    refs = input_block.get("refs")
    if not isinstance(refs, list):
        raise ExecutionPackageError(
            "package context.input_refs.refs must be a list",
            code="package_input_refs_invalid",
        )
    for ref in refs:
        if not isinstance(ref, dict):
            raise ExecutionPackageError(
                "each input_refs.refs entry must be an object",
                code="package_input_refs_invalid",
            )
        rel = str(ref.get("path") or "")
        expected = str(ref.get("sha256") or "")
        if not rel or not expected:
            raise ExecutionPackageError(
                "each input ref requires path and sha256",
                code="package_input_refs_invalid",
            )
        path = (workspace / rel).resolve()
        if not path.is_file():
            raise ExecutionPackageError(
                f"authoritative input missing: {rel}",
                code="package_input_missing",
            )
        actual = digest_file(path)
        if actual != expected:
            raise ExecutionPackageError(
                f"authoritative input digest mismatch for {rel}: "
                f"expected {expected}, got {actual}",
                code="package_input_drift",
            )

    resolved = package.resolved_config
    if resolved is None:
        raise ExecutionPackageError(
            "prepared package is missing embedded execution config",
            code="package_config_missing",
        )

    validate_resolved_config_against_package(
        resolved,
        package,
        workspace=workspace,
    )


def verify_package_context_snapshot_exact(package: LoadedExecutionPackage) -> dict[str, Any]:
    """Require the live workspace context snapshot to match the package exactly."""

    context = package.manifest.get("context")
    if not isinstance(context, dict):
        raise ExecutionPackageError(
            "package context block missing",
            code="package_context_missing",
        )
    expected_snapshot = str(context.get("context_snapshot_digest") or "")
    if not expected_snapshot:
        raise ExecutionPackageError(
            "prepared package missing context_snapshot_digest",
            code="package_context_incomplete",
        )

    package_binding = _load_package_snapshot_binding(package)
    resolved = package.resolved_config
    if resolved is None:
        raise ExecutionPackageError(
            "prepared package is missing embedded execution config",
            code="package_config_missing",
        )
    workspace = package.workspace_path
    _, _, actual_snapshot, _ = build_initial_context_snapshot_binding_with_diagnostics(
        resolved,
        workspace=workspace,
    )
    if actual_snapshot != expected_snapshot:
        raise ExecutionPackageError(
            f"context_snapshot digest mismatch: expected {expected_snapshot}, "
            f"got {actual_snapshot}",
            code="package_context_drift",
        )
    return package_binding


def authorized_paths_from_accepted_result(
    accepted: dict[str, Any],
    *,
    workspace: Path,
) -> set[str]:
    """Derive authorized workspace paths from content-bound ``workspace_changes``."""

    return set(
        workspace_changes_from_accepted_result(
            accepted,
            workspace=workspace,
        )
    )


def workspace_changes_from_accepted_result(
    accepted: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, dict[str, Any]]:
    """Return content-bound workspace changes keyed by canonical relative path.

    ``workspace_changes`` is required. Path authorization from ``output_refs`` is
    not accepted.
    """

    from top_down_planning.config.snapshot_policy import (
        CanonicalPathError,
        canonicalize_evidence_ref,
    )

    raw = accepted.get("workspace_changes")
    if not isinstance(raw, dict):
        raise ExecutionPackageError(
            "accepted_result missing workspace_changes for content-bound authorization",
            code="sub_tdp_upstream_invalid",
        )
    changes: dict[str, dict[str, Any]] = {}
    for path, change in raw.items():
        if not isinstance(change, dict):
            raise ExecutionPackageError(
                f"accepted_result workspace_changes[{path!r}] must be an object",
                code="sub_tdp_upstream_invalid",
            )
        text = str(path or "").strip()
        if not text:
            continue
        try:
            canonical = canonicalize_evidence_ref(text, workspace=workspace)
        except CanonicalPathError as exc:
            raise ExecutionPackageError(
                f"accepted_result workspace_changes path invalid: {text!r}",
                code="sub_tdp_upstream_invalid",
            ) from exc
        operation = str(change.get("operation") or "").strip()
        if operation == "delete":
            raise ExecutionPackageError(
                "accepted_result workspace_changes delete operation is not supported "
                "until production can capture delete tombstones",
                code="sub_tdp_upstream_invalid",
            )
        if operation not in {"write"}:
            raise ExecutionPackageError(
                f"accepted_result workspace_changes[{path!r}] missing operation",
                code="sub_tdp_upstream_invalid",
            )
        if not str(change.get("sha256") or "").strip():
            raise ExecutionPackageError(
                f"accepted_result workspace_changes[{path!r}] missing sha256",
                code="sub_tdp_upstream_invalid",
            )
        changes[canonical] = dict(change)
    return changes


def topo_sort_sub_tdp_items(
    items: list[dict[str, Any]],
    *,
    item_id: Callable[[dict[str, Any]], str],
    depends_on_ids: Callable[[dict[str, Any]], list[str]],
) -> list[dict[str, Any]]:
    """Return items in dependency order for workspace-change succession.

    Raises when ``depends_on`` forms a cycle among the provided items.
    """

    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item_id(item) or "").strip()
        if key:
            indexed[key] = item

    depends_on: dict[str, list[str]] = {}
    for key, item in indexed.items():
        raw_deps = depends_on_ids(item)
        depends_on[key] = [
            str(dep).strip() for dep in raw_deps if str(dep).strip() in indexed
        ]

    indegree = {key: 0 for key in indexed}
    for key, deps in depends_on.items():
        for dep in deps:
            indegree[key] += 1

    queue = sorted([key for key, count in indegree.items() if count == 0])
    ordered: list[dict[str, Any]] = []
    while queue:
        key = queue.pop(0)
        ordered.append(indexed[key])
        for peer_key, deps in depends_on.items():
            if key not in deps:
                continue
            indegree[peer_key] -= 1
            if indegree[peer_key] == 0:
                queue.append(peer_key)
        queue.sort()

    if len(ordered) != len(indexed):
        raise ExecutionPackageError(
            "sub_tdp dependency cycle prevents workspace-change succession ordering",
            code="sub_tdp_upstream_invalid",
        )
    return ordered


def _snapshot_digest_for_authorized_workspace(
    authorized_changes: dict[str, dict[str, Any]],
    *,
    workspace: Path,
    resolved_config: dict[str, Any],
    verify_workspace_bytes: bool = True,
) -> str:
    """Return context snapshot digest when workspace bytes match authorized changes."""

    if verify_workspace_bytes and authorized_changes:
        verify_workspace_matches_authorized_changes(
            sorted(authorized_changes),
            authorized_changes=authorized_changes,
            workspace=workspace,
        )
    _, digest, _ = recompute_context_snapshot_binding_with_diagnostics(
        resolved_config,
        workspace=workspace,
    )
    snapshot_digest = str(digest or "").strip()
    if not snapshot_digest:
        raise ExecutionPackageError(
            "failed to compute context snapshot digest for merged workspace baseline",
            code="sub_tdp_upstream_invalid",
        )
    return snapshot_digest


def _cumulative_snapshot_after_units(
    unit_keys: list[str],
    indexed: dict[str, dict[str, Any]],
    *,
    item_id: Callable[[dict[str, Any]], str],
    depends_on_ids: Callable[[dict[str, Any]], list[str]],
    accepted_result: Callable[[dict[str, Any]], dict[str, Any]],
    initial_snapshot_digest: str,
    workspace: Path,
    resolved_config: dict[str, Any],
) -> str:
    """Return context snapshot digest after merging workspace changes for unit_keys."""

    if not unit_keys:
        return str(initial_snapshot_digest or "").strip()
    key_set = {key for key in unit_keys if key in indexed}
    subset = [indexed[key] for key in sorted(key_set)]

    def filtered_depends_on(item: dict[str, Any]) -> list[str]:
        return [
            str(dep).strip()
            for dep in depends_on_ids(item)
            if str(dep).strip() in key_set
        ]

    ordered = order_workspace_succession_items(
        subset,
        item_id=item_id,
        depends_on_ids=filtered_depends_on,
        accepted_result=accepted_result,
        initial_snapshot_digest=initial_snapshot_digest,
        workspace=workspace,
        resolved_config=resolved_config,
        allow_composite_joins=False,
    )
    merged: dict[str, dict[str, Any]] = {}
    cumulative = str(initial_snapshot_digest or "").strip()
    for record in ordered:
        merged, cumulative = merge_accepted_result_workspace_changes(
            merged,
            accepted_result(record),
            cumulative_snapshot_digest=cumulative,
            workspace=workspace,
        )
    if not merged:
        return cumulative
    return _snapshot_digest_for_authorized_workspace(
        merged,
        workspace=workspace,
        resolved_config=resolved_config,
        verify_workspace_bytes=False,
    )


def order_workspace_succession_items(
    items: list[dict[str, Any]],
    *,
    item_id: Callable[[dict[str, Any]], str],
    depends_on_ids: Callable[[dict[str, Any]], list[str]],
    accepted_result: Callable[[dict[str, Any]], dict[str, Any]],
    initial_snapshot_digest: str,
    workspace: Path,
    resolved_config: dict[str, Any],
    allow_composite_joins: bool = True,
) -> list[dict[str, Any]]:
    """Order items for workspace-change succession using snapshot lineage and depends_on.

    Roots use ``baseline_context_snapshot_digest == initial_snapshot_digest`` (the
    prepared package context snapshot for parent sub-TDP merges). Otherwise ordering
    follows a prior ``final_context_snapshot_digest`` or, for composite multi-result
    baseline joins, merged workspace lineage from all other items in the set.
    Package ``depends_on`` edges are additional constraints. Raises on cycles,
    duplicate unit ids, ambiguous lineage, or unrepresentable baseline joins.
    """

    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item_id(item) or "").strip()
        if not key:
            continue
        if key in indexed:
            raise ExecutionPackageError(
                f"duplicate baseline accepted result for unit {key!r}",
                code="sub_tdp_upstream_invalid",
            )
        indexed[key] = item

    initial = str(initial_snapshot_digest or "").strip()
    final_by_unit: dict[str, str] = {}
    for key, item in indexed.items():
        accepted = accepted_result(item)
        if not isinstance(accepted, dict):
            raise ExecutionPackageError(
                f"accepted_result missing for unit {key!r}",
                code="sub_tdp_upstream_invalid",
            )
        final = str(accepted.get("final_context_snapshot_digest") or "").strip()
        if not final:
            raise ExecutionPackageError(
                f"accepted_result missing final_context_snapshot_digest for unit {key!r}",
                code="sub_tdp_upstream_invalid",
            )
        final_by_unit[key] = final

    lineage_preds: dict[str, list[str]] = {}
    for key, item in indexed.items():
        accepted = accepted_result(item)
        baseline = str(accepted.get("baseline_context_snapshot_digest") or "").strip()
        if not baseline:
            raise ExecutionPackageError(
                f"accepted_result missing baseline_context_snapshot_digest for unit {key!r}",
                code="sub_tdp_upstream_invalid",
            )
        if baseline == initial:
            continue
        single_final_preds = [
            unit
            for unit, final in final_by_unit.items()
            if final == baseline and unit in indexed and unit != key
        ]
        if len(single_final_preds) > 1:
            raise ExecutionPackageError(
                f"ambiguous snapshot predecessors for unit {key!r}",
                code="sub_tdp_upstream_invalid",
            )
        if len(single_final_preds) == 1:
            lineage_preds[key] = [single_final_preds[0]]
            continue
        if not allow_composite_joins:
            raise ExecutionPackageError(
                f"unit {key!r} baseline does not match package initial snapshot "
                "or a single prior final_context_snapshot_digest",
                code="sub_tdp_upstream_invalid",
            )
        others = sorted([unit for unit in indexed if unit != key])
        if not others:
            raise ExecutionPackageError(
                f"unit {key!r} baseline does not match package initial snapshot",
                code="sub_tdp_upstream_invalid",
            )
        merged_digest = _cumulative_snapshot_after_units(
            others,
            indexed,
            item_id=item_id,
            depends_on_ids=depends_on_ids,
            accepted_result=accepted_result,
            initial_snapshot_digest=initial,
            workspace=workspace,
            resolved_config=resolved_config,
        )
        if merged_digest == baseline:
            lineage_preds[key] = others
            continue
        raise ExecutionPackageError(
            f"unit {key!r} baseline does not match package initial snapshot, "
            "a single prior final_context_snapshot_digest, or merged workspace "
            "lineage from other units",
            code="sub_tdp_upstream_invalid",
        )

    depends_on: dict[str, list[str]] = {}
    for key, item in indexed.items():
        raw_deps = depends_on_ids(item)
        deps = [str(dep).strip() for dep in raw_deps if str(dep).strip() in indexed]
        for pred in lineage_preds.get(key, []):
            if pred not in deps:
                deps.append(pred)
        depends_on[key] = deps

    indegree = {key: 0 for key in indexed}
    for key, deps in depends_on.items():
        indegree[key] = len(deps)

    queue = sorted([key for key, count in indegree.items() if count == 0])
    ordered: list[dict[str, Any]] = []
    while queue:
        key = queue.pop(0)
        ordered.append(indexed[key])
        for peer_key, deps in depends_on.items():
            if key not in deps:
                continue
            indegree[peer_key] -= 1
            if indegree[peer_key] == 0:
                queue.append(peer_key)
        queue.sort()

    if len(ordered) != len(indexed):
        raise ExecutionPackageError(
            "workspace succession cycle prevents baseline ordering",
            code="sub_tdp_upstream_invalid",
        )
    return ordered


def _topo_sort_baseline_wrappers(
    wrappers: list[dict[str, Any]],
    *,
    unit_depends_on: dict[str, list[str]],
    initial_snapshot_digest: str,
    workspace: Path,
    resolved_config: dict[str, Any],
) -> list[dict[str, Any]]:
    valid = [
        wrapper
        for wrapper in wrappers
        if isinstance(wrapper, dict) and isinstance(wrapper.get("accepted_result"), dict)
    ]
    return order_workspace_succession_items(
        valid,
        item_id=lambda wrapper: str(
            (wrapper.get("accepted_result") or {}).get("unit_id") or ""
        ).strip(),
        depends_on_ids=lambda wrapper: [
            str(dep).strip()
            for dep in unit_depends_on.get(
                str((wrapper.get("accepted_result") or {}).get("unit_id") or "").strip(),
                [],
            )
        ],
        accepted_result=lambda wrapper: wrapper["accepted_result"],
        initial_snapshot_digest=initial_snapshot_digest,
        workspace=workspace,
        resolved_config=resolved_config,
    )


def merge_authorized_workspace_changes(
    existing: dict[str, dict[str, Any]],
    incoming: dict[str, dict[str, Any]],
    *,
    allow_same_path_overwrite: bool = False,
) -> dict[str, dict[str, Any]]:
    """Merge content-bound workspace changes; reject unrelated hash conflicts."""

    merged = dict(existing)
    for path, change in incoming.items():
        new_op = str(change.get("operation") or "").strip()
        if new_op == "delete":
            raise ExecutionPackageError(
                "accepted workspace_changes delete operation is not supported "
                "until production can capture delete tombstones",
                code="sub_tdp_upstream_invalid",
            )
        if new_op != "write":
            raise ExecutionPackageError(
                f"accepted workspace change for {path} missing operation",
                code="sub_tdp_upstream_invalid",
            )
        prior = merged.get(path)
        if prior is None:
            merged[path] = dict(change)
            continue
        existing_op = str(prior.get("operation") or "").strip()
        if existing_op != new_op:
            raise ExecutionPackageError(
                f"conflicting accepted workspace operations for {path}",
                code="package_context_drift",
            )
        if str(prior.get("sha256") or "") != str(change.get("sha256") or ""):
            if not allow_same_path_overwrite:
                raise ExecutionPackageError(
                    f"conflicting accepted workspace hashes for {path}",
                    code="package_context_drift",
                )
        merged[path] = dict(change)
    return merged


def merge_accepted_result_workspace_changes(
    merged: dict[str, dict[str, Any]],
    accepted_result: dict[str, Any],
    *,
    cumulative_snapshot_digest: str,
    workspace: Path,
) -> tuple[dict[str, dict[str, Any]], str]:
    """Apply one accepted result as a snapshot transition in dependency order."""

    baseline = str(
        accepted_result.get("baseline_context_snapshot_digest") or ""
    ).strip()
    final = str(accepted_result.get("final_context_snapshot_digest") or "").strip()
    if not final:
        raise ExecutionPackageError(
            "accepted_result missing final_context_snapshot_digest",
            code="sub_tdp_upstream_invalid",
        )
    changes = workspace_changes_from_accepted_result(
        accepted_result,
        workspace=workspace,
    )
    allow_overwrite = baseline == cumulative_snapshot_digest
    merged = merge_authorized_workspace_changes(
        merged,
        changes,
        allow_same_path_overwrite=allow_overwrite,
    )
    return merged, final


def _authorized_workspace_changes_from_baseline(
    baseline_wrappers: list[dict[str, Any]],
    *,
    workspace: Path,
    initial_snapshot_digest: str,
    resolved_config: dict[str, Any],
    unit_depends_on: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    from top_down_planning.package.lineage import verify_upstream_accepted_result_binding

    if not str(initial_snapshot_digest or "").strip():
        raise ExecutionPackageError(
            "package initial context_snapshot_digest is required for baseline workspace merge",
            code="sub_tdp_upstream_invalid",
        )

    ordered_wrappers = _topo_sort_baseline_wrappers(
        baseline_wrappers,
        unit_depends_on=unit_depends_on or {},
        initial_snapshot_digest=initial_snapshot_digest,
        workspace=workspace,
        resolved_config=resolved_config,
    )
    merged: dict[str, dict[str, Any]] = {}
    cumulative = str(initial_snapshot_digest or "").strip()
    for wrapper in ordered_wrappers:
        verify_upstream_accepted_result_binding(wrapper)
        accepted = wrapper["accepted_result"]
        if not str(accepted.get("child_run_id") or "").strip():
            raise ExecutionPackageError(
                "baseline accepted_result missing child_run_id",
                code="sub_tdp_upstream_invalid",
            )
        merged, cumulative = merge_accepted_result_workspace_changes(
            merged,
            accepted,
            cumulative_snapshot_digest=cumulative,
            workspace=workspace,
        )
    return merged


def verify_merged_baseline_workspace_bytes(
    baseline_wrappers: list[dict[str, Any]],
    *,
    workspace: Path,
    initial_snapshot_digest: str,
    resolved_config: dict[str, Any],
    unit_depends_on: dict[str, list[str]] | None = None,
    production_overlay: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Verify current workspace once against the fully merged baseline map."""

    authorized = _authorized_workspace_changes_from_baseline(
        baseline_wrappers,
        workspace=workspace,
        initial_snapshot_digest=initial_snapshot_digest,
        resolved_config=resolved_config,
        unit_depends_on=unit_depends_on,
    )
    if production_overlay is not None:
        authorized = merge_parent_integration_workspace_evidence(
            authorized,
            production_overlay,
            workspace=workspace,
        )
    if authorized:
        verify_workspace_matches_authorized_changes(
            sorted(authorized),
            authorized_changes=authorized,
            workspace=workspace,
        )
    return authorized


def baseline_auth_params_from_binding(
    binding: dict[str, Any],
) -> tuple[str, dict[str, list[str]], dict[str, Any], dict[str, Any]]:
    """Return initial snapshot, depends_on map, resolved config, and package units."""

    manifest_path = str(binding.get("manifest_path") or "").strip()
    if not manifest_path:
        raise ExecutionPackageError(
            "package_binding missing manifest_path",
            code="sub_tdp_upstream_invalid",
        )
    from top_down_planning.package.loader import ExecutionPackageLoader

    try:
        package = ExecutionPackageLoader().load(
            Path(manifest_path).parent,
            verify_workspace=False,
        )
    except (OSError, ValueError, TypeError) as exc:
        raise ExecutionPackageError(
            f"failed to load package from manifest_path: {exc}",
            code="sub_tdp_upstream_invalid",
        ) from exc
    initial_snapshot = str(
        (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
    )
    if not initial_snapshot:
        raise ExecutionPackageError(
            "package missing context_snapshot_digest",
            code="sub_tdp_upstream_invalid",
        )
    resolved_config = package.resolved_config
    if not isinstance(resolved_config, dict):
        raise ExecutionPackageError(
            "prepared package is missing embedded execution config",
            code="package_config_missing",
        )
    unit_depends_on = {
        unit_id: list(unit.depends_on) for unit_id, unit in package.units.items()
    }
    return initial_snapshot, unit_depends_on, resolved_config, package.units


def merge_parent_integration_workspace_evidence(
    merged: dict[str, dict[str, Any]],
    production: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, dict[str, Any]]:
    """Overlay live production output evidence atop a merged workspace-change map.

    Used for parent integration (child closure + parent batches) and for paused
    child resume (baseline closure + the child's own in-progress production).
    """

    from core_tools.persistence import digest_file
    from top_down_planning.config.context_digests import latest_output_evidence_by_path

    overlay: dict[str, dict[str, Any]] = {}
    for path, entry in latest_output_evidence_by_path(
        production,
        workspace=workspace,
    ).items():
        expected = str(entry.get("sha256") or "").strip()
        if not expected:
            continue
        target = workspace / path
        if not target.is_file():
            continue
        if digest_file(target) != expected:
            continue
        overlay[path] = {
            "operation": "write",
            "sha256": expected,
            "size": int(entry.get("size") or target.stat().st_size),
            "snapshot_ref": str(entry.get("snapshot_ref") or entry.get("id") or path),
        }
    if not overlay:
        return merged
    return merge_authorized_workspace_changes(
        merged,
        overlay,
        allow_same_path_overwrite=True,
    )


def verify_workspace_matches_authorized_changes(
    paths: list[str],
    *,
    authorized_changes: dict[str, dict[str, Any]],
    workspace: Path,
) -> None:
    unauthorized: list[str] = []
    for path in paths:
        change = authorized_changes.get(path)
        if change is None:
            unauthorized.append(path)
            continue
        operation = str(change.get("operation") or "").strip()
        if operation == "delete":
            raise ExecutionPackageError(
                "accepted workspace_changes delete operation is not supported "
                "until production can capture delete tombstones",
                code="sub_tdp_upstream_invalid",
            )
        if operation != "write":
            raise ExecutionPackageError(
                f"accepted workspace change for {path} missing operation",
                code="sub_tdp_upstream_invalid",
            )
        target = workspace / path
        if not target.is_file():
            raise ExecutionPackageError(
                f"workspace path {path} missing for accepted write",
                code="package_context_drift",
            )
        actual = digest_file(target)
        expected = str(change.get("sha256") or "").strip()
        if not expected:
            raise ExecutionPackageError(
                f"accepted workspace change for {path} missing sha256",
                code="sub_tdp_upstream_invalid",
            )
        if actual != expected:
            raise ExecutionPackageError(
                f"workspace bytes for {path} do not match accepted sha256",
                code="package_context_drift",
            )
    if unauthorized:
        joined = ", ".join(unauthorized)
        raise ExecutionPackageError(
            f"context snapshot resource drift not authorized by workspace baseline "
            f"accepted results: {joined}",
            code="package_context_drift",
        )


def verify_package_context_snapshot_with_baseline(
    package: LoadedExecutionPackage,
    *,
    store: Any,
    baseline_wrappers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Allow resource drift when covered by cumulative baseline accepted results.

    ``baseline_wrappers`` is the cumulative workspace baseline lineage used for
    context authorization (direct deps plus previously accepted sibling/closure
    results). Empty wrappers require an exact package snapshot match.

    Authorization is content-bound: changed resource paths must appear in the
    baseline workspace_changes map and current workspace bytes must match the
    accepted write sha256.
    """

    del store  # call-site keeps store for symmetry; auth uses immutable records only
    resolved = package.resolved_config
    if resolved is None:
        raise ExecutionPackageError(
            "prepared package is missing embedded execution config",
            code="package_config_missing",
        )
    workspace = package.workspace_path
    package_binding = _load_package_snapshot_binding(package)
    new_binding, _, new_snapshot_digest, _ = (
        build_initial_context_snapshot_binding_with_diagnostics(
            resolved,
            workspace=workspace,
        )
    )
    expected_snapshot = str(
        (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
    )
    if new_snapshot_digest == expected_snapshot:
        return new_binding

    changed_paths = diff_snapshot_binding_paths(package_binding, new_binding)
    if not changed_paths:
        raise ExecutionPackageError(
            f"context_snapshot digest mismatch without binding path changes: "
            f"expected {expected_snapshot}, got {new_snapshot_digest}",
            code="package_context_drift",
        )

    evidence_gaps, context_mutations = split_unauthorized_snapshot_paths(
        changed_paths,
        binding=package_binding,
        other_binding=new_binding,
    )
    if context_mutations:
        joined = ", ".join(context_mutations)
        raise ExecutionPackageError(
            f"context snapshot drift on non-resource bindings is not allowed: {joined}",
            code="package_context_drift",
        )

    authorized_changes = _authorized_workspace_changes_from_baseline(
        baseline_wrappers,
        workspace=workspace,
        initial_snapshot_digest=expected_snapshot,
        resolved_config=resolved,
        unit_depends_on={
            unit_id: list(unit.depends_on) for unit_id, unit in package.units.items()
        },
    )
    verify_workspace_matches_authorized_changes(
        evidence_gaps,
        authorized_changes=authorized_changes,
        workspace=workspace,
    )
    return new_binding


def verify_package_authoritative_inputs(
    package: LoadedExecutionPackage,
) -> dict[str, Any]:
    """Verify immutable contract and exact context snapshot; return binding baseline."""

    verify_package_immutable_contract(package)
    return verify_package_context_snapshot_exact(package)


def _aggregate_input_digest(context: dict[str, Any]) -> str:
    input_block = context.get("input_refs")
    if isinstance(input_block, dict):
        return str(input_block.get("aggregate_digest") or "")
    return ""


__all__ = [
    "authorized_paths_from_accepted_result",
    "merge_accepted_result_workspace_changes",
    "merge_authorized_workspace_changes",
    "baseline_auth_params_from_binding",
    "merge_parent_integration_workspace_evidence",
    "order_workspace_succession_items",
    "topo_sort_sub_tdp_items",
    "validate_resolved_config_against_package",
    "verify_merged_baseline_workspace_bytes",
    "verify_package_authoritative_inputs",
    "verify_package_context_snapshot_exact",
    "verify_package_context_snapshot_with_baseline",
    "verify_package_immutable_contract",
    "verify_workspace_matches_authorized_changes",
    "workspace_changes_from_accepted_result",
]
