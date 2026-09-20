"""Shared fault injection for post-commit provider session sync tests."""

from __future__ import annotations

from collections.abc import Callable

from core_tools.provider.errors import ProviderSessionMismatchError
from top_down_planning.orchestrator.phase_action_domain_audit import (
    phase_action_domain_proven_by_audit,
)
from top_down_planning.orchestrator.session_events import sync_persisted_session_id
from top_down_planning.persistence import FileRunStore


def sync_failure_after_domain_commit(
    store: FileRunStore,
    run_id: str,
    phase_action_id: str,
) -> Callable[..., str]:
    """Raise ``ProviderSessionMismatchError`` once domain commit is audit-proven."""

    def _sync_with_post_commit_failure(
        bound_provider,
        bound_store,
        bound_run_id,
        session_id,
        *,
        role: str,
    ) -> str:
        if phase_action_domain_proven_by_audit(bound_store, bound_run_id, phase_action_id):
            raise ProviderSessionMismatchError(
                "simulated post-commit session sync failure",
                session_id=session_id,
            )
        return sync_persisted_session_id(
            bound_provider,
            bound_store,
            bound_run_id,
            session_id,
            role=role,
        )

    return _sync_with_post_commit_failure
