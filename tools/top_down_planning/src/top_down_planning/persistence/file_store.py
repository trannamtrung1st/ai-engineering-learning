"""File-backed run store with journaled commits and path containment."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from top_down_planning.domain.models import Plan
from core_tools.persistence import (
    PersistenceError,
    RunNotFoundError,
    StoreRevisionConflictError,
    assert_next_revision,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    digest_file,
    dump_yaml,
    exclusive_file_lock,
    load_yaml,
    require_revision_field,
)
from top_down_planning.persistence.capabilities import new_capability_record
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.digests import compute_config_digest, compute_plan_digest
from top_down_planning.persistence.path_ids import validate_store_id

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
    context_digest: str,
    phase: str = "planning",
    workspace: str,
) -> dict[str, Any]:
    now = _utc_now()
    return {
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
            "items_added": 0,
        },
        "production_loop": {
            "current_batch_agent_turns": 0,
        },
        "created_at": now,
        "updated_at": now,
        "workspace": workspace,
    }


class FileRunStore:
    """Canonical file layout under ``<root>/<run-id>/``."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    def run_dir(self, run_id: str) -> Path:
        validated = validate_store_id(run_id, label="run_id")
        return self._assert_contained(self._root / validated)

    def create_run(
        self,
        run_id: str,
        *,
        plan: Plan | dict[str, Any],
        resolved_config: dict[str, Any],
        input_digest: str,
        output_goal_digest: str,
        context_digest: str,
        phase: str = "planning",
        production: dict[str, Any] | None = None,
        workspace: str,
        invocation: dict[str, Any],
    ) -> dict[str, Any]:
        validated_run_id = validate_store_id(run_id, label="run_id")
        if not input_digest or not output_goal_digest or not context_digest:
            raise PersistenceError(
                "input_digest, output_goal_digest, and context_digest are required"
            )
        if not workspace or not str(workspace).strip():
            raise PersistenceError("workspace is required")
        if not isinstance(invocation, dict):
            raise PersistenceError("invocation metadata is required")

        final_run_dir = self.run_dir(validated_run_id)
        if final_run_dir.exists():
            raise PersistenceError(f"run already exists: {validated_run_id}")

        staging_dir = self._assert_contained(self._root / f".creating-{validated_run_id}")
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        plan_payload = plan.to_dict() if isinstance(plan, Plan) else dict(plan)
        config_digest = compute_config_digest(resolved_config)
        plan_digest = compute_plan_digest(plan_payload)
        run_record = new_run_record(
            validated_run_id,
            input_digest=input_digest,
            output_goal_digest=output_goal_digest,
            config_digest=config_digest,
            plan_digest=plan_digest,
            context_digest=context_digest,
            phase=phase,
            workspace=workspace,
        )

        try:
            staging_dir.mkdir(parents=True)
            (staging_dir / "reviews").mkdir()
            (staging_dir / "capabilities").mkdir()
            (staging_dir / "artifacts").mkdir()
            atomic_write_text(
                staging_dir / "resolved-config.yaml",
                dump_yaml(resolved_config) + "\n",
            )
            atomic_write_json(staging_dir / "run.json", run_record)
            atomic_write_json(staging_dir / "plan.json", plan_payload)
            atomic_write_json(
                staging_dir / "production.json",
                production if production is not None else dict(_EMPTY_PRODUCTION),
            )
            atomic_write_json(staging_dir / "invocation.json", invocation)
            (staging_dir / "events.jsonl").write_text("", encoding="utf-8")
            staging_dir.rename(final_run_dir)
        except Exception:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            raise

        self.commit(
            validated_run_id,
            CommitSpec(
                events=[
                    {
                        "type": "run_created",
                        "run_id": validated_run_id,
                        "revision": run_record["revision"],
                        "phase": run_record["phase"],
                    }
                ]
            ),
        )
        return self.load_run(validated_run_id)

    def load_run(self, run_id: str) -> dict[str, Any]:
        self._recover_incomplete_transactions(run_id)
        return self._read_json(self._run_path(run_id))

    def load_plan(self, run_id: str) -> dict[str, Any]:
        self._recover_incomplete_transactions(run_id)
        return self._read_json(self._plan_path(run_id))

    def load_plan_model(self, run_id: str) -> Plan:
        return Plan.from_dict(self.load_plan(run_id))

    def load_production(self, run_id: str) -> dict[str, Any]:
        self._recover_incomplete_transactions(run_id)
        return self._read_json(self._production_path(run_id))

    def commit(self, run_id: str, spec: CommitSpec) -> dict[str, Any]:
        validated_run_id = validate_store_id(run_id, label="run_id")
        run_dir = self.run_dir(validated_run_id)
        if not run_dir.is_dir():
            raise RunNotFoundError(validated_run_id, "run directory missing", runs_root=self._root)

        lock_path = self._assert_contained(run_dir / ".commit.lock")
        with exclusive_file_lock(lock_path):
            return self._commit_locked(validated_run_id, run_dir, spec)

    def _commit_locked(
        self,
        validated_run_id: str,
        run_dir: Path,
        spec: CommitSpec,
    ) -> dict[str, Any]:
        self._recover_incomplete_transactions(validated_run_id)

        if spec.run is not None:
            expected = spec.run_expected_revision
            if expected is None:
                raise PersistenceError("commit with run payload requires run_expected_revision")
            current_revision = int(self.load_run(validated_run_id)["revision"])
            if current_revision != expected:
                raise StoreRevisionConflictError(expected, current_revision)
            next_revision = require_revision_field(spec.run, "run")
            assert_next_revision(expected, next_revision)
            run_payload = dict(spec.run)
            run_payload["revision"] = next_revision
            run_payload["updated_at"] = _utc_now()
        else:
            run_payload = None

        if spec.plan is not None:
            expected = spec.plan_expected_revision
            if expected is None:
                raise PersistenceError("commit with plan payload requires plan_expected_revision")
            current_revision = int(self.load_plan(validated_run_id)["revision"])
            if current_revision != expected:
                raise StoreRevisionConflictError(expected, current_revision)
            next_revision = require_revision_field(spec.plan, "plan")
            assert_next_revision(expected, next_revision)
            plan_payload = dict(spec.plan)
            plan_payload["revision"] = next_revision
        else:
            plan_payload = None

        if spec.production is not None:
            expected = spec.production_expected_revision
            if expected is None:
                raise PersistenceError(
                    "commit with production payload requires production_expected_revision"
                )
            current_revision = int(self.load_production(validated_run_id)["revision"])
            if current_revision != expected:
                raise StoreRevisionConflictError(expected, current_revision)
            next_revision = require_revision_field(spec.production, "production")
            assert_next_revision(expected, next_revision)
            production_payload = dict(spec.production)
            production_payload["revision"] = next_revision
        else:
            production_payload = None

        review_payloads: list[tuple[str, dict[str, Any]]] = []
        for review in spec.reviews:
            review_id = review.get("id")
            if not review_id:
                raise PersistenceError("review record requires id")
            validated_review_id = validate_store_id(str(review_id), label="review_id")
            review_payloads.append((validated_review_id, dict(review)))

        txn_id = uuid.uuid4().hex
        staging_dir = self._assert_contained(run_dir / f".txn-{txn_id}")
        journal_path = staging_dir / "journal.json"
        backups_dir = staging_dir / "backups"
        staging_dir.mkdir()
        backups_dir.mkdir()
        staged_files: list[dict[str, Any]] = []

        journal_events = [dict(event) for event in spec.events]
        for event in journal_events:
            event["txn_id"] = txn_id

        committed = False
        try:
            if run_payload is not None:
                staged_path = staging_dir / "run.json"
                atomic_write_json(staged_path, run_payload)
                staged_files.append(
                    {
                        "kind": "run",
                        "name": "run.json",
                        "digest": digest_file(staged_path),
                    }
                )

            if plan_payload is not None:
                staged_path = staging_dir / "plan.json"
                atomic_write_json(staged_path, plan_payload)
                staged_files.append(
                    {
                        "kind": "plan",
                        "name": "plan.json",
                        "digest": digest_file(staged_path),
                    }
                )

            if production_payload is not None:
                staged_path = staging_dir / "production.json"
                atomic_write_json(staged_path, production_payload)
                staged_files.append(
                    {
                        "kind": "production",
                        "name": "production.json",
                        "digest": digest_file(staged_path),
                    }
                )

            for review_id, review_payload in review_payloads:
                staged_name = f"review__{review_id}.json"
                staged_path = staging_dir / staged_name
                atomic_write_json(staged_path, review_payload)
                staged_files.append(
                    {
                        "kind": "review",
                        "name": staged_name,
                        "review_id": review_id,
                        "digest": digest_file(staged_path),
                    }
                )

            journal: dict[str, Any] = {
                "txn_id": txn_id,
                "status": "prepared",
                "files": staged_files,
                "events": journal_events,
                "backups": [],
                "replaced": [],
            }
            atomic_write_json(journal_path, journal)

            journal["status"] = "replacing"
            atomic_write_json(journal_path, journal)

            for entry in staged_files:
                staged_path = staging_dir / entry["name"]
                if entry["kind"] == "review":
                    reviews_dir = self.reviews_dir(validated_run_id)
                    reviews_dir.mkdir(parents=True, exist_ok=True)
                    dest = reviews_dir / f"{entry['review_id']}.json"
                else:
                    dest = run_dir / entry["name"]
                self._assert_contained(dest)
                if dest.exists():
                    backup_path = backups_dir / entry["name"]
                    shutil.copy2(dest, backup_path)
                    journal["backups"].append(entry["name"])
                    atomic_write_json(journal_path, journal)
                staged_path.replace(dest)
                journal["replaced"].append(entry["name"])
                atomic_write_json(journal_path, journal)

            journal["status"] = "appending_events"
            atomic_write_json(journal_path, journal)

            if journal_events:
                events_path = self._events_path(validated_run_id)
                with events_path.open("a", encoding="utf-8") as handle:
                    for event in journal_events:
                        payload = dict(event)
                        payload.setdefault("ts", _utc_now())
                        handle.write(json.dumps(payload, sort_keys=True) + "\n")

            journal["status"] = "committed"
            atomic_write_json(journal_path, journal)
            committed = True
        finally:
            if committed and staging_dir.exists():
                shutil.rmtree(staging_dir)

        result: dict[str, Any] = {"ok": True}
        if run_payload is not None:
            result["run_revision"] = int(run_payload["revision"])
        if plan_payload is not None:
            result["plan_revision"] = int(plan_payload["revision"])
        if production_payload is not None:
            result["production_revision"] = int(production_payload["revision"])
        return result

    def save_run(self, run_id: str, run: dict[str, Any], expected_revision: int) -> int:
        payload = dict(run)
        next_revision = require_revision_field(payload, "run")
        assert_next_revision(expected_revision, next_revision)
        self.commit(
            run_id,
            CommitSpec(run=payload, run_expected_revision=expected_revision),
        )
        return next_revision

    def save_plan(self, run_id: str, plan: dict[str, Any], expected_revision: int) -> int:
        payload = dict(plan)
        next_revision = require_revision_field(payload, "plan")
        assert_next_revision(expected_revision, next_revision)
        self.commit(
            run_id,
            CommitSpec(plan=payload, plan_expected_revision=expected_revision),
        )
        return next_revision

    def save_plan_model(self, run_id: str, plan: Plan, expected_revision: int) -> int:
        return self.save_plan(run_id, plan.to_dict(), expected_revision)

    def save_production(
        self, run_id: str, production: dict[str, Any], expected_revision: int
    ) -> int:
        payload = dict(production)
        next_revision = require_revision_field(payload, "production")
        assert_next_revision(expected_revision, next_revision)
        self.commit(
            run_id,
            CommitSpec(
                production=payload,
                production_expected_revision=expected_revision,
            ),
        )
        return next_revision

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        self.commit(run_id, CommitSpec(events=[dict(event)]))

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self._events_path(run_id)
        if not path.exists():
            raise RunNotFoundError(run_id, "events.jsonl missing", runs_root=self._root)
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(json.loads(line))
        return events

    def load_resolved_config(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / "resolved-config.yaml"
        if not path.exists():
            raise RunNotFoundError(
                run_id,
                "resolved-config.yaml missing",
                runs_root=self._root,
            )
        payload = load_yaml(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PersistenceError("resolved-config.yaml must contain a mapping")
        return payload

    def save_invocation(self, run_id: str, invocation: dict[str, Any]) -> None:
        """Persist CLI invocation metadata (presentation/store bootstrap; not digested)."""

        path = self.run_dir(run_id) / "invocation.json"
        if not path.parent.is_dir():
            raise RunNotFoundError(run_id, "run directory missing", runs_root=self._root)
        atomic_write_json(path, invocation)

    def load_invocation(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / "invocation.json"
        if not path.exists():
            raise RunNotFoundError(
                run_id,
                "invocation.json missing",
                runs_root=self._root,
            )
        return self._read_json(path)

    def reviews_dir(self, run_id: str) -> Path:
        return self._assert_contained(self.run_dir(run_id) / "reviews")

    def capabilities_dir(self, run_id: str) -> Path:
        return self._assert_contained(self.run_dir(run_id) / "capabilities")

    def artifacts_dir(self, run_id: str) -> Path:
        return self._assert_contained(self.run_dir(run_id) / "artifacts")

    def create_capability(
        self,
        run_id: str,
        *,
        role: str,
        phase: str,
        allowed_ops: frozenset[str],
        session_id: str,
        session_kind: str = "primary",
        loop_id: str | None = None,
    ) -> tuple[str, dict[str, Any], str]:
        capability_id, record, raw_secret = new_capability_record(
            run_id=run_id,
            role=role,
            phase=phase,
            allowed_ops=allowed_ops,
            session_id=session_id,
            session_kind=session_kind,
            loop_id=loop_id,
        )
        capabilities_dir = self.capabilities_dir(run_id)
        capabilities_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(capabilities_dir / f"{capability_id}.json", record)
        return capability_id, record, raw_secret

    def load_capability(self, run_id: str, capability_id: str) -> dict[str, Any]:
        validated_id = validate_store_id(capability_id, label="capability_id")
        path = self.capabilities_dir(run_id) / f"{validated_id}.json"
        if not path.exists():
            raise RunNotFoundError(
                run_id,
                f"capability {validated_id} missing",
                runs_root=self._root,
            )
        return self._read_json(path)

    def list_capabilities(self, run_id: str) -> list[dict[str, Any]]:
        capabilities_dir = self.capabilities_dir(run_id)
        if not capabilities_dir.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(capabilities_dir.glob("*.json")):
            records.append(self._read_json(path))
        return records

    def revoke_capability(self, run_id: str, capability_id: str) -> None:
        record = self.load_capability(run_id, capability_id)
        record["revoked"] = True
        validated_id = validate_store_id(capability_id, label="capability_id")
        atomic_write_json(self.capabilities_dir(run_id) / f"{validated_id}.json", record)

    def revoke_capabilities_for_session(self, run_id: str, session_id: str) -> None:
        normalized_session_id = str(session_id).strip()
        for record in self.list_capabilities(run_id):
            if record.get("revoked") is True:
                continue
            if str(record.get("session_id") or "").strip() != normalized_session_id:
                continue
            capability_id = str(record.get("id") or "")
            if capability_id:
                self.revoke_capability(run_id, capability_id)

    def artifact_path(self, run_id: str, snapshot_id: str, filename: str) -> Path:
        validated_snapshot_id = validate_store_id(snapshot_id, label="snapshot_id")
        validated_filename = validate_store_id(filename, label="artifact_filename")
        return self._assert_contained(
            self.artifacts_dir(run_id) / validated_snapshot_id / validated_filename
        )

    def write_artifact_bytes(
        self,
        run_id: str,
        snapshot_id: str,
        filename: str,
        data: bytes,
    ) -> str:
        path = self.artifact_path(run_id, snapshot_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, data)
        return str(
            Path("artifacts")
            / validate_store_id(snapshot_id, label="snapshot_id")
            / validate_store_id(filename, label="artifact_filename")
        )

    def save_review(self, run_id: str, review: dict[str, Any]) -> None:
        review_id = review.get("id")
        if not review_id:
            raise PersistenceError("review record requires id")
        self.commit(run_id, CommitSpec(reviews=[dict(review)]))

    def load_review(self, run_id: str, review_id: str) -> dict[str, Any]:
        validated_review_id = validate_store_id(review_id, label="review_id")
        path = self.reviews_dir(run_id) / f"{validated_review_id}.json"
        if not path.exists():
            raise RunNotFoundError(
                run_id,
                f"review {validated_review_id} missing",
                runs_root=self._root,
            )
        return self._read_json(path)

    def list_reviews(self, run_id: str) -> list[dict[str, Any]]:
        reviews_dir = self.reviews_dir(run_id)
        if not reviews_dir.is_dir():
            return []
        reviews: list[dict[str, Any]] = []
        for path in sorted(reviews_dir.glob("*.json")):
            reviews.append(self._read_json(path))
        return reviews

    def _recover_incomplete_transactions(self, run_id: str) -> None:
        run_dir = self.run_dir(run_id)
        if not run_dir.is_dir():
            return
        for staging_dir in sorted(run_dir.glob(".txn-*")):
            if not staging_dir.is_dir():
                continue
            self._recover_transaction_dir(run_id, run_dir, staging_dir)

    def _recover_transaction_dir(
        self,
        run_id: str,
        run_dir: Path,
        staging_dir: Path,
    ) -> None:
        journal_path = staging_dir / "journal.json"
        if not journal_path.is_file():
            shutil.rmtree(staging_dir)
            return

        journal = self._read_json(journal_path)
        status = str(journal.get("status") or "prepared")
        txn_id = str(journal.get("txn_id") or "")
        staged_files = list(journal.get("files") or [])
        journal_events = list(journal.get("events") or [])
        backups_dir = staging_dir / "backups"
        replaced = list(journal.get("replaced") or [])

        if status in {"prepared", "replacing"}:
            all_names = {str(entry.get("name") or "") for entry in staged_files}
            replaced_names = {str(name) for name in replaced}
            if (
                status == "replacing"
                and all_names
                and replaced_names >= all_names
                and self._verify_replaced_files_match_staged(
                    run_dir,
                    staged_files,
                    replaced,
                )
            ):
                if txn_id and journal_events:
                    self._ensure_events_appended(run_id, txn_id, journal_events)
                shutil.rmtree(staging_dir)
                return
            self._rollback_replaced_files(
                run_dir,
                staged_files,
                self._collect_names_for_rollback(
                    run_dir,
                    staged_files,
                    replaced,
                ),
                backups_dir,
            )
            shutil.rmtree(staging_dir)
            return

        if status == "appending_events":
            if txn_id and journal_events:
                self._ensure_events_appended(run_id, txn_id, journal_events)
            shutil.rmtree(staging_dir)
            return

        if status == "committed":
            shutil.rmtree(staging_dir)
            return

        shutil.rmtree(staging_dir)

    def _destination_for_staged_entry(self, run_dir: Path, entry: dict[str, Any]) -> Path:
        if entry.get("kind") == "review":
            review_id = str(entry.get("review_id") or "")
            return self._assert_contained(run_dir / "reviews" / f"{review_id}.json")
        return self._assert_contained(run_dir / str(entry.get("name") or ""))

    def _verify_replaced_files_match_staged(
        self,
        run_dir: Path,
        staged_files: list[dict[str, Any]],
        replaced: list[str],
    ) -> bool:
        entry_by_name = {str(entry.get("name") or ""): entry for entry in staged_files}
        for name in replaced:
            entry = entry_by_name.get(name)
            if entry is None:
                return False
            dest = self._destination_for_staged_entry(run_dir, entry)
            if not dest.is_file():
                return False
            expected_digest = str(entry.get("digest") or "")
            if not expected_digest or digest_file(dest) != expected_digest:
                return False
        return True

    def _collect_names_for_rollback(
        self,
        run_dir: Path,
        staged_files: list[dict[str, Any]],
        replaced: list[str],
    ) -> list[str]:
        names = {str(name) for name in replaced}
        for entry in staged_files:
            name = str(entry.get("name") or "")
            if not name or name in names:
                continue
            expected_digest = str(entry.get("digest") or "")
            if not expected_digest:
                continue
            dest = self._destination_for_staged_entry(run_dir, entry)
            if dest.is_file() and digest_file(dest) == expected_digest:
                names.add(name)
        return sorted(names)

    def _rollback_replaced_files(
        self,
        run_dir: Path,
        staged_files: list[dict[str, Any]],
        replaced: list[str],
        backups_dir: Path,
    ) -> None:
        entry_by_name = {str(entry.get("name") or ""): entry for entry in staged_files}
        for name in replaced:
            entry = entry_by_name.get(name)
            if entry is None:
                continue
            if entry.get("kind") == "review":
                review_id = str(entry.get("review_id") or "")
                dest = self._assert_contained(run_dir / "reviews" / f"{review_id}.json")
            else:
                dest = self._assert_contained(run_dir / name)
            backup_path = backups_dir / name
            if backup_path.is_file():
                shutil.copy2(backup_path, dest)
            elif dest.exists():
                dest.unlink()

    def _ensure_events_appended(
        self,
        run_id: str,
        txn_id: str,
        journal_events: list[dict[str, Any]],
    ) -> None:
        events_path = self._events_path(run_id)
        existing_txn_ids: set[str] = set()
        if events_path.is_file():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                event_txn_id = payload.get("txn_id")
                if event_txn_id is not None:
                    existing_txn_ids.add(str(event_txn_id))

        if txn_id in existing_txn_ids:
            return

        with events_path.open("a", encoding="utf-8") as handle:
            for event in journal_events:
                payload = dict(event)
                payload.setdefault("txn_id", txn_id)
                payload.setdefault("ts", _utc_now())
                handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def _assert_contained(self, path: Path) -> Path:
        resolved = path.resolve()
        root = self._root.resolve()
        if resolved == root:
            return resolved
        if not resolved.is_relative_to(root):
            raise PersistenceError(f"path escapes run store root: {path}")
        return resolved

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
            raise RunNotFoundError(
                run_id,
                f"missing {path.name}",
                runs_root=self._root,
            )

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RunNotFoundError(
                path.parent.name,
                f"missing {path.name}",
                runs_root=self._root,
            ) from exc
        except json.JSONDecodeError as exc:
            raise PersistenceError(f"failed to load {path}: {exc}") from exc
