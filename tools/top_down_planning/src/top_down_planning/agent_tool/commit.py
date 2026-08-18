"""Map authorized agent mutations onto a freshness-bound CommitSpec."""

from __future__ import annotations

from typing import Any

from core_tools.persistence import StoreRevisionConflictError

from top_down_planning.agent_tool.authorization import MutationAuthorization
from top_down_planning.agent_tool.errors import CapabilityDeniedError, RevisionConflictError
from top_down_planning.persistence.commit import CommitSpec, StoreAuthorizationConflictError
from top_down_planning.persistence.interface import RunStore


def commit_authorized(
    store: RunStore,
    run_id: str,
    spec: CommitSpec,
    auth: MutationAuthorization,
    *,
    conflict_action: str | None = None,
) -> dict[str, Any]:
    """Commit with authorization freshness bound under the run lock."""

    bound = CommitSpec(
        events=spec.events,
        run=spec.run,
        run_expected_revision=(
            spec.run_expected_revision
            if spec.run_expected_revision is not None
            else auth.run_revision
        ),
        plan=spec.plan,
        plan_expected_revision=spec.plan_expected_revision,
        production=spec.production,
        production_expected_revision=spec.production_expected_revision,
        resolved_config=spec.resolved_config,
        invocation=spec.invocation,
        reviews=spec.reviews,
        review_expected_revisions=spec.review_expected_revisions,
        authorized_capability_id=auth.capability_id,
        authorized_phase=auth.phase,
    )
    try:
        return store.commit(run_id, bound)
    except StoreRevisionConflictError as exc:
        raise RevisionConflictError(
            str(exc),
            expected=exc.expected,
            actual=exc.actual,
            action=conflict_action,
        ) from exc
    except StoreAuthorizationConflictError as exc:
        raise CapabilityDeniedError(str(exc), operation=auth.operation) from exc
