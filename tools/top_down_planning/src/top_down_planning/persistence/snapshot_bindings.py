"""Cross-snapshot digest binding validation for journaled commits."""

from __future__ import annotations

from typing import Any

from core_tools.persistence import PersistenceError

from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
    compute_output_digest,
    compute_plan_digest,
)


def validate_snapshot_digest_bindings(
    run: dict[str, Any],
    *,
    plan: dict[str, Any] | None,
    production: dict[str, Any] | None,
    resolved_config: dict[str, Any] | None,
) -> None:
    """Require run digest fields to match the prospective canonical snapshots."""

    digests = run.get("digests")
    if not isinstance(digests, dict):
        raise PersistenceError("run.digests must be an object")

    if plan is not None:
        expected_plan = str(digests.get("plan") or "").strip()
        actual_plan = compute_plan_digest(plan)
        if not expected_plan or actual_plan != expected_plan:
            raise PersistenceError("run.digests.plan does not match plan snapshot")

    if resolved_config is not None:
        expected_contract = str(digests.get("config_contract") or "").strip()
        actual_contract = compute_config_contract_digest(resolved_config)
        if not expected_contract or actual_contract != expected_contract:
            raise PersistenceError(
                "run.digests.config_contract does not match resolved-config snapshot"
            )
        expected_execution = str(digests.get("config_execution") or "").strip()
        actual_execution = compute_config_execution_digest(resolved_config)
        if not expected_execution or actual_execution != expected_execution:
            raise PersistenceError(
                "run.digests.config_execution does not match resolved-config snapshot"
            )

    if production is not None:
        output_digest = str(digests.get("output") or "").strip()
        if output_digest:
            actual_output = compute_output_digest(production)
            if actual_output != output_digest:
                raise PersistenceError(
                    "run.digests.output does not match production snapshot"
                )


def bind_run_digests_for_plan_update(
    run: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Return a run payload with ``digests.plan`` updated for a plan revision bump."""

    run_patch = dict(run)
    digests = dict(run_patch.get("digests") or {})
    digests["plan"] = compute_plan_digest(plan)
    run_patch["digests"] = digests
    return run_patch


def bind_run_digests_for_production_update(
    run: dict[str, Any],
    production: dict[str, Any],
) -> dict[str, Any]:
    """Return a run payload with ``digests.output`` updated when output binding exists."""

    run_patch = dict(run)
    digests = dict(run_patch.get("digests") or {})
    if str(digests.get("output") or "").strip():
        digests["output"] = compute_output_digest(production)
    run_patch["digests"] = digests
    return run_patch


def bind_run_digests_for_config_update(
    run: dict[str, Any],
    resolved_config: dict[str, Any],
) -> dict[str, Any]:
    """Return a run payload with config digest fields updated."""

    run_patch = dict(run)
    digests = dict(run_patch.get("digests") or {})
    digests["config_contract"] = compute_config_contract_digest(resolved_config)
    digests["config_execution"] = compute_config_execution_digest(resolved_config)
    run_patch["digests"] = digests
    return run_patch
