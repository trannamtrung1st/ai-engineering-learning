"""Validate execution-time config and authoritative inputs against the package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    """Derive authorized workspace paths from an immutable accepted-result record."""

    from top_down_planning.config.snapshot_policy import (
        CanonicalPathError,
        canonicalize_evidence_ref,
    )

    authorized: set[str] = set()
    for output in accepted.get("output_refs") or []:
        if not isinstance(output, dict):
            continue
        ref_text = str(output.get("ref") or "").strip()
        if not ref_text:
            continue
        try:
            authorized.add(canonicalize_evidence_ref(ref_text, workspace=workspace))
        except CanonicalPathError:
            continue
    return authorized


def _authorized_paths_from_baseline(
    baseline_wrappers: list[dict[str, Any]],
    *,
    workspace: Path,
) -> set[str]:
    from top_down_planning.package.lineage import verify_upstream_accepted_result_binding

    authorized: set[str] = set()
    for wrapper in baseline_wrappers:
        verify_upstream_accepted_result_binding(wrapper)
        accepted = wrapper["accepted_result"]
        if not str(accepted.get("child_run_id") or "").strip():
            raise ExecutionPackageError(
                "baseline accepted_result missing child_run_id",
                code="sub_tdp_upstream_invalid",
            )
        authorized |= authorized_paths_from_accepted_result(
            accepted,
            workspace=workspace,
        )
    return authorized


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

    authorized = _authorized_paths_from_baseline(
        baseline_wrappers,
        workspace=workspace,
    )
    unauthorized = [path for path in evidence_gaps if path not in authorized]
    if unauthorized:
        joined = ", ".join(unauthorized)
        raise ExecutionPackageError(
            f"context snapshot resource drift not authorized by workspace baseline "
            f"accepted results: {joined}",
            code="package_context_drift",
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
    "validate_resolved_config_against_package",
    "verify_package_authoritative_inputs",
    "verify_package_context_snapshot_exact",
    "verify_package_context_snapshot_with_baseline",
    "verify_package_immutable_contract",
]
