"""File-backed run store (proposal §18)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from top_down_planning.domain.models import Plan
from core_tools.persistence import (
    atomic_write_json,
    atomic_write_text,
    dump_yaml,
    load_yaml,
)
from top_down_planning.persistence.digests import compute_config_digest, compute_plan_digest
from top_down_planning.persistence.errors import (
    PersistenceError,
    RunNotFoundError,
    StoreRevisionConflictError,
)

_EMPTY_PRODUCTION: dict[str, Any] = {
    "revision": 0,
    "output_revision": 0,
    "batches": [],
    "dispositions": {},
    "output_evidence": [],
    "amendment_requests": [],
    "pending_amendment_id": None,
    "reconciliation_reports": [],
    "completion_claim": None,
    "blocker_report": None,
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_record(
    run_id: str,
    *,
    input_digest: str,
    output_goal_digest: str,
    config_digest: str,
    plan_digest: str,
    context_digest: str | None = None,
    phase: str = "planning",
    workspace: str | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    record = {
        "id": run_id,
        "revision": 0,
        "status": "running",
        "phase": phase,
        "outcome": None,
        "digests": {
            "input": input_digest,
            "output_goal": output_goal_digest,
            "config": config_digest,
            "plan": plan_digest,
            "context": context_digest,
        },
        "sessions": {
            "primary_planner_session_id": None,
            "primary_producer_session_id": None,
        },
        "planning": {
            "agent_turns": 0,
            "expansion_iterations": 0,
        },
        "production_loop": {
            "current_batch_agent_turns": 0,
        },
        "created_at": now,
        "updated_at": now,
    }
    if workspace is not None:
        record["workspace"] = workspace
    return record


def _require_revision_field(payload: dict[str, Any], label: str) -> int:
    if "revision" not in payload:
        raise PersistenceError(f"{label} payload must include an explicit revision")
    return int(payload["revision"])


def _assert_next_revision(expected_revision: int, next_revision: int) -> None:
    if next_revision != expected_revision + 1:
        raise StoreRevisionConflictError(expected_revision + 1, next_revision)


class FileRunStore:
    """Canonical file layout under ``<root>/<run-id>/``."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def run_dir(self, run_id: str) -> Path:
        return self._root / run_id

    def create_run(
        self,
        run_id: str,
        *,
        plan: Plan | dict[str, Any],
        resolved_config: dict[str, Any],
        input_digest: str,
        output_goal_digest: str,
        context_digest: str | None = None,
        phase: str = "planning",
        production: dict[str, Any] | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        if not input_digest or not output_goal_digest:
            raise PersistenceError("input_digest and output_goal_digest are required")

        run_path = self.run_dir(run_id)
        if run_path.exists():
            raise PersistenceError(f"run already exists: {run_id}")

        plan_payload = plan.to_dict() if isinstance(plan, Plan) else dict(plan)
        config_digest = compute_config_digest(resolved_config)
        plan_digest = compute_plan_digest(plan_payload)
        run_record = new_run_record(
            run_id,
            input_digest=input_digest,
            output_goal_digest=output_goal_digest,
            config_digest=config_digest,
            plan_digest=plan_digest,
            context_digest=context_digest,
            phase=phase,
            workspace=workspace,
        )

        run_path.mkdir(parents=True)
        (run_path / "reviews").mkdir()
        atomic_write_text(
            run_path / "resolved-config.yaml",
            dump_yaml(resolved_config) + "\n",
        )
        atomic_write_json(run_path / "run.json", run_record)
        atomic_write_json(run_path / "plan.json", plan_payload)
        atomic_write_json(
            run_path / "production.json",
            production if production is not None else dict(_EMPTY_PRODUCTION),
        )
        (run_path / "events.jsonl").write_text("", encoding="utf-8")
        self.append_event(
            run_id,
            {
                "type": "run_created",
                "run_id": run_id,
                "revision": run_record["revision"],
                "phase": run_record["phase"],
            },
        )
        return run_record

    def load_run(self, run_id: str) -> dict[str, Any]:
        return self._read_json(self._run_path(run_id))

    def save_run(self, run_id: str, run: dict[str, Any], expected_revision: int) -> int:
        current_revision = int(self.load_run(run_id)["revision"])
        if current_revision != expected_revision:
            raise StoreRevisionConflictError(expected_revision, current_revision)

        next_revision = _require_revision_field(run, "run")
        _assert_next_revision(expected_revision, next_revision)

        payload = dict(run)
        payload["revision"] = next_revision
        payload["updated_at"] = _utc_now()
        atomic_write_json(self._run_path(run_id), payload)
        return next_revision

    def load_plan(self, run_id: str) -> dict[str, Any]:
        return self._read_json(self._plan_path(run_id))

    def load_plan_model(self, run_id: str) -> Plan:
        return Plan.from_dict(self.load_plan(run_id))

    def save_plan(self, run_id: str, plan: dict[str, Any], expected_revision: int) -> int:
        current_revision = int(self.load_plan(run_id)["revision"])
        if current_revision != expected_revision:
            raise StoreRevisionConflictError(expected_revision, current_revision)

        next_revision = _require_revision_field(plan, "plan")
        _assert_next_revision(expected_revision, next_revision)

        payload = dict(plan)
        payload["revision"] = next_revision
        atomic_write_json(self._plan_path(run_id), payload)
        return next_revision

    def save_plan_model(self, run_id: str, plan: Plan, expected_revision: int) -> int:
        return self.save_plan(run_id, plan.to_dict(), expected_revision)

    def load_production(self, run_id: str) -> dict[str, Any]:
        return self._read_json(self._production_path(run_id))

    def save_production(
        self, run_id: str, production: dict[str, Any], expected_revision: int
    ) -> int:
        current_revision = int(self.load_production(run_id)["revision"])
        if current_revision != expected_revision:
            raise StoreRevisionConflictError(expected_revision, current_revision)

        next_revision = _require_revision_field(production, "production")
        _assert_next_revision(expected_revision, next_revision)

        payload = dict(production)
        payload["revision"] = next_revision
        atomic_write_json(self._production_path(run_id), payload)
        return next_revision

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        path = self._events_path(run_id)
        if not path.exists():
            raise RunNotFoundError(run_id, "events.jsonl missing")
        payload = dict(event)
        payload.setdefault("ts", _utc_now())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self._events_path(run_id)
        if not path.exists():
            raise RunNotFoundError(run_id, "events.jsonl missing")
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(json.loads(line))
        return events

    def load_resolved_config(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / "resolved-config.yaml"
        if not path.exists():
            raise RunNotFoundError(run_id, "resolved-config.yaml missing")
        payload = load_yaml(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PersistenceError("resolved-config.yaml must contain a mapping")
        return payload

    def reviews_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "reviews"

    def save_review(self, run_id: str, review: dict[str, Any]) -> None:
        review_id = review.get("id")
        if not review_id:
            raise PersistenceError("review record requires id")
        reviews_dir = self.reviews_dir(run_id)
        if not reviews_dir.is_dir():
            raise RunNotFoundError(run_id, "reviews/ missing")
        atomic_write_json(reviews_dir / f"{review_id}.json", dict(review))

    def load_review(self, run_id: str, review_id: str) -> dict[str, Any]:
        path = self.reviews_dir(run_id) / f"{review_id}.json"
        if not path.exists():
            raise RunNotFoundError(run_id, f"review {review_id} missing")
        return self._read_json(path)

    def list_reviews(self, run_id: str) -> list[dict[str, Any]]:
        reviews_dir = self.reviews_dir(run_id)
        if not reviews_dir.is_dir():
            return []
        reviews: list[dict[str, Any]] = []
        for path in sorted(reviews_dir.glob("*.json")):
            reviews.append(self._read_json(path))
        return reviews

    def _run_path(self, run_id: str) -> Path:
        path = self.run_dir(run_id) / "run.json"
        self._require_file(path, run_id)
        return path

    def _plan_path(self, run_id: str) -> Path:
        path = self.run_dir(run_id) / "plan.json"
        self._require_file(path, run_id)
        return path

    def _production_path(self, run_id: str) -> Path:
        path = self.run_dir(run_id) / "production.json"
        self._require_file(path, run_id)
        return path

    def _events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def _require_file(self, path: Path, run_id: str) -> None:
        if not path.exists():
            raise RunNotFoundError(run_id, f"missing {path.name}")

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RunNotFoundError(path.parent.name, f"missing {path.name}") from exc
        except json.JSONDecodeError as exc:
            raise PersistenceError(f"failed to load {path}: {exc}") from exc
