"""Atomic resume configuration persistence (proposal §8.4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core_tools.persistence import StoreRevisionConflictError

from top_down_planning.config.resume_policy import (
    ResumeConfigComparison,
    compare_resume_configs,
    validate_resume_config_comparison,
)
from top_down_planning.domain.run_ownership import (
    RunOwnershipError,
    assert_expected_run_revision,
    assert_no_live_process_owns_run,
    resolve_run_dir,
)
from top_down_planning.invocation import (
    merge_invocation_metadata,
    sync_invocation_notifications_from_config,
    sync_invocation_observability_from_config,
)
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
)
from top_down_planning.persistence.file_store import FileRunStore

__all__ = [
    "ResumeConfigCommitError",
    "ResumeConfigUpdate",
    "apply_resume_config_atomic",
    "build_resume_config_commit_spec",
    "validate_and_prepare_resume_config_update",
]


class ResumeConfigCommitError(ValueError):
    """Resume config validation or persistence precondition failure."""


@dataclass(frozen=True)
class ResumeConfigUpdate:
    resolved_config: dict[str, Any]
    invocation: dict[str, Any]
    config_changes: dict[str, dict[str, Any]]
    comparison: ResumeConfigComparison
    config_contract_digest: str
    config_execution_digest: str


def validate_and_prepare_resume_config_update(
    *,
    stored_config: dict[str, Any],
    candidate_config: dict[str, Any],
    stored_invocation: dict[str, Any],
    candidate_invocation: dict[str, Any],
    consumed_limits: dict[str, int] | None = None,
    contract_digest_may_change: bool = False,
) -> ResumeConfigUpdate:
    """Validate resume config changes and build the persistence payload."""

    comparison = validate_resume_config_comparison(
        compare_resume_configs(stored_config, candidate_config),
        consumed_limits=consumed_limits,
        candidate_config=candidate_config,
        allow_contract_and_model_changes=contract_digest_may_change,
    )
    if not comparison.ok:
        detail = comparison.errors[0] if comparison.errors else "resume config change blocked"
        raise ResumeConfigCommitError(detail)
    if comparison.contract_digest_changed and not contract_digest_may_change:
        raise ResumeConfigCommitError("config_contract must remain unchanged during resume")

    invocation = sync_invocation_notifications_from_config(
        sync_invocation_observability_from_config(
            merge_invocation_metadata(stored_invocation, candidate_invocation),
            candidate_config,
        ),
        candidate_config,
    )
    config_changes = {
        change.path: {
            "from": change.stored_value,
            "to": change.candidate_value,
        }
        for change in comparison.allowed_changes
    }
    return ResumeConfigUpdate(
        resolved_config=candidate_config,
        invocation=invocation,
        config_changes=config_changes,
        comparison=comparison,
        config_contract_digest=compute_config_contract_digest(candidate_config),
        config_execution_digest=compute_config_execution_digest(candidate_config),
    )


def build_resume_config_commit_spec(
    *,
    run: dict[str, Any],
    resolved_config: dict[str, Any],
    invocation: dict[str, Any],
    run_expected_revision: int,
    contract_digest_may_change: bool = False,
) -> CommitSpec:
    """Build a journaled commit for accepted resume config updates."""

    stored_contract = str((run.get("digests") or {}).get("config_contract") or "")
    new_contract = compute_config_contract_digest(resolved_config)
    if stored_contract and stored_contract != new_contract and not contract_digest_may_change:
        raise ResumeConfigCommitError("config_contract must remain unchanged during resume")

    run_payload = dict(run)
    digests = dict(run_payload.get("digests") or {})
    digests["config_contract"] = new_contract
    digests["config_execution"] = compute_config_execution_digest(resolved_config)
    run_payload["digests"] = digests
    next_revision = int(run_expected_revision) + 1
    run_payload["revision"] = next_revision

    return CommitSpec(
        run=run_payload,
        run_expected_revision=run_expected_revision,
        resolved_config=resolved_config,
        invocation=invocation,
    )


def apply_resume_config_atomic(
    store: FileRunStore,
    run_id: str,
    *,
    resolved_config: dict[str, Any],
    invocation: dict[str, Any],
    run_expected_revision: int,
) -> dict[str, Any]:
    """Persist accepted resume config, execution digest, and invocation atomically."""

    run = store.load_run(run_id)
    try:
        assert_expected_run_revision(run, run_expected_revision)
        run_dir = resolve_run_dir(store, run_id)
        if run_dir is not None:
            assert_no_live_process_owns_run(run_id, run_dir=run_dir)
    except RunOwnershipError as exc:
        raise ResumeConfigCommitError(str(exc)) from exc

    spec = build_resume_config_commit_spec(
        run=run,
        resolved_config=resolved_config,
        invocation=invocation,
        run_expected_revision=run_expected_revision,
    )
    try:
        result = store.commit(run_id, spec)
    except StoreRevisionConflictError as exc:
        raise ResumeConfigCommitError(
            f"resume config apply revision conflict: expected {exc.expected}, "
            f"found {exc.actual}"
        ) from exc

    return {
        "run_revision": int(result["run_revision"]),
        "config_contract_digest": compute_config_contract_digest(resolved_config),
        "config_execution_digest": compute_config_execution_digest(resolved_config),
    }
