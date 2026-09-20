"""Stub provider with explicit session-id alias chains for lineage tests."""

from __future__ import annotations

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderSessionError
from top_down_planning.domain.models import Plan
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config, plan_root_item


class ForcedIdStub(StubProvider):
    def __init__(
        self,
        *,
        forced_primary_id: str | None = None,
        forced_reviewer_id: str | None = None,
    ) -> None:
        super().__init__()
        self.forced_primary_id = forced_primary_id
        self.forced_reviewer_id = forced_reviewer_id
        self.aliases: dict[str, str] = {}

    def canonical_session_id(self, session_id: str) -> str:
        current = session_id
        seen: set[str] = set()
        while current in self.aliases and current not in seen:
            seen.add(current)
            current = self.aliases[current]
        return current

    def start_primary_session(self, role, request, *, model=None):
        if self.forced_primary_id is not None:
            return self.forced_primary_id
        return super().start_primary_session(role, request, model=model)

    def get_session_reference(self, session_id: str):
        canonical = self.canonical_session_id(session_id)
        key = session_id
        if canonical in self._sessions:
            key = canonical
        elif session_id in self._sessions:
            key = session_id
        else:
            for alias, target in self.aliases.items():
                if self.canonical_session_id(target) == canonical and alias in self._sessions:
                    key = alias
                    break
        session = self._sessions.get(key)
        if session is None:
            raise ProviderSessionError(
                f"unknown provider session: {session_id}",
                session_id=session_id,
            )
        return {
            "provider": "stub",
            "session_id": canonical,
            "role": session.role,
            "kind": session.kind,
            "model": session.model,
            "turn_count": len(session.history),
        }


def create_minimal_planning_run(store: FileRunStore, run_id: str) -> None:
    root = plan_root_item(title="Root", outcome="Root.")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
