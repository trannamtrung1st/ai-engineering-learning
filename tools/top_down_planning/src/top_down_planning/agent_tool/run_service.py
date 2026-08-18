"""Agent run status service (proposal §8, §20)."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.views import build_run_status_view
from top_down_planning.persistence.interface import RunStore


class RunAgentService:
    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def status(self) -> dict[str, Any]:
        snapshot = self._store.load_canonical_snapshot(self._run_id)
        agent_requests_dir = self._store.agent_requests_dir(self._run_id)
        run_path = self._store.run_dir(self._run_id)
        return {
            "ok": True,
            "run_path": str(run_path),
            "agent_requests_dir": str(agent_requests_dir),
            "run": build_run_status_view(
                snapshot.run,
                plan_revision=snapshot.plan.get("revision"),
            ),
        }
