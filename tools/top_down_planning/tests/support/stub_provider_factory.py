"""Provider factory that returns fresh StubProvider instances per engine phase."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from core_tools.provider import StubProvider
from top_down_planning.domain.session_bindings import resumable_binding_provider_session_id
from top_down_planning.orchestrator.reviewer_session import reviewer_loop_binding
from tests.helpers import done_events
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import get_primary_binding


class _SharedScriptStubProvider(StubProvider):
    """Stub provider that draws turn scripts from a shared factory queue."""

    def __init__(self, factory: RotatingStubProviderFactory) -> None:
        super().__init__()
        self._factory = factory

    def _resolve_script(self, session_id: str) -> list[dict[str, Any]]:
        session = self._require_session(session_id)
        scripted, hook = self._factory._pop_next_script(session_id)
        session.pending_hook = hook
        return scripted


class RotatingStubProviderFactory:
    """Create a new StubProvider for each factory call with shared turn scripting."""

    def __init__(self, store: FileRunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id
        self._turn_scripts: list[
            tuple[str | None, list[dict[str, Any]], Callable[[], None] | None]
        ] = []
        self._shared_index = 0
        self._autofill_mutate: Callable[[], None] | None = None
        self.instances: list[StubProvider] = []

    def register_autofill_mutate(self, mutate: Callable[[], None] | None) -> None:
        self._autofill_mutate = mutate

    def script_turn(
        self,
        events: list[dict[str, Any]],
        *,
        mutate_store: Callable[[], None] | None = None,
        session_id: str | None = None,
    ) -> None:
        self._turn_scripts.append((session_id, events, mutate_store))

    def script_session_turn(
        self,
        session_id: str,
        events: list[dict[str, Any]],
        *,
        mutate_store: Callable[[], None] | None = None,
    ) -> None:
        self.script_turn(events, mutate_store=mutate_store, session_id=session_id)

    def script_many_turns(self, events: list[dict[str, Any]], count: int) -> None:
        for _ in range(count):
            self.script_turn(events)

    def _pop_next_script(
        self,
        active_session_id: str,
    ) -> tuple[list[dict[str, Any]], Callable[[], None] | None]:
        while self._shared_index < len(self._turn_scripts):
            session_id, events, mutate_store = self._turn_scripts[self._shared_index]
            self._shared_index += 1
            if session_id is not None and session_id != active_session_id:
                continue
            return copy.deepcopy(events), mutate_store
        return done_events(text="shared-stub-bookkeeping"), self._autofill_mutate

    def _bootstrap_bound_sessions(self, provider: StubProvider) -> None:
        """Register durable session ids without consuming scripted turns."""

        run = self._store.load_run(self._run_id)
        for role in ("producer", "planner"):
            binding = get_primary_binding(run, role)
            if binding is None:
                continue
            session_id = binding.provider_session_id
            if not session_id:
                continue
            provider._ensure_durable_session(  # noqa: SLF001 — test harness
                session_id,
                role=role,
                kind="primary",
            )

        for loop_payload in self._store.list_reviews(self._run_id):
            binding = reviewer_loop_binding(loop_payload)
            if binding is None:
                continue
            session_id = resumable_binding_provider_session_id(binding)
            if not session_id:
                continue
            provider._ensure_durable_session(  # noqa: SLF001
                session_id,
                role="reviewer",
                kind="reviewer",
            )

        max_stub_index = provider._counter  # noqa: SLF001
        for session_id in provider._sessions:  # noqa: SLF001
            if session_id.startswith("stub-session-"):
                try:
                    max_stub_index = max(max_stub_index, int(session_id.rsplit("-", 1)[-1]))
                except ValueError:
                    continue
        provider._counter = max_stub_index  # noqa: SLF001

    def create_provider(self, _config: dict[str, Any], _workspace: Any) -> StubProvider:
        provider = _SharedScriptStubProvider(self)
        self._bootstrap_bound_sessions(provider)
        self.instances.append(provider)
        return provider

    def __call__(self, config: dict[str, Any], workspace: Any) -> StubProvider:
        return self.create_provider(config, workspace)
