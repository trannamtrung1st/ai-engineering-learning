"""Agent run status service (proposal §8, §20)."""

from __future__ import annotations

from typing import Any

from top_down_planning.persistence.interface import RunStore


class RunAgentService:
    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def status(self) -> dict[str, Any]:
        run = self._store.load_run(self._run_id)
        plan = self._store.load_plan(self._run_id)
        return {
            "ok": True,
            "run": {
                "id": run["id"],
                "revision": run["revision"],
                "status": run.get("status"),
                "phase": run.get("phase"),
                "outcome": run.get("outcome"),
                "plan_revision": plan.get("revision"),
            },
        }
