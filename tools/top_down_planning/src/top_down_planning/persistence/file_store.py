"""File-backed run store with journaled commits and path containment."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from top_down_planning.domain.models import Plan
from core_tools.persistence import (
    PersistenceError,
    RunNotFoundError,
    StoreRevisionConflictError,
    TransactionRecoveryError,
    assert_next_revision,
    atomic_write_json,
    atomic_write_text,
    digest_file,
    dump_yaml,
    exclusive_create_bytes,
    exclusive_file_lock,
    load_yaml,
    require_revision_field,
)
from top_down_planning.persistence.capabilities import new_capability_record

AGENT_REQUESTS_DIR = "agent-requests"
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.journal_schema import (
    journal_file_entry_as_dict,
    parse_recovery_journal,
)
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
    compute_plan_digest,
)
from top_down_planning.persistence.path_ids import validate_run_id, validate_store_id
from top_down_planning.domain.plan_schema import (
    PLAN_SCHEMA_VERSION,
    UNSUPPORTED_PLAN_SCHEMA_MESSAGE,
    UnsupportedPlanSchemaVersionError,
    validate_plan_schema_version,
)
from top_down_planning.persistence.run_schema import (
    CURRENT_RUN_SCHEMA_VERSION,
    validate_run_digests,
    validate_run_schema_version,
)
from top_down_planning.config.binding_validation import validate_context_snapshot_binding
from top_down_planning.domain.run_lifecycle import (
    RunLifecycleError,
    validate_run_lifecycle_invariants,
)
from top_down_planning.domain.session_recovery_state import validate_session_recovery_fields
from top_down_planning.persistence.session_bindings import (
    normalize_sessions_for_runtime,
    initial_structured_sessions,
    normalize_review_record_for_runtime,
    review_record_for_persistence,
    sessions_for_persistence,
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
    "sub_tdps": None,
}

_KNOWN_TXN_STATUSES = frozenset(
    {"prepared", "replacing", "appending_events", "committed"}
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_plan_payload(plan: Plan | dict[str, Any]) -> dict[str, Any]:
    if isinstance(plan, Plan):
        if plan.schema_version != PLAN_SCHEMA_VERSION:
            raise UnsupportedPlanSchemaVersionError(UNSUPPORTED_PLAN_SCHEMA_MESSAGE)
        return plan.to_dict()
    model = Plan.from_dict(dict(plan))
    return model.to_dict()


def new_run_record(
    run_id: str,
    *,
    input_digest: str,
    output_goal_digest: str,
    config_contract_digest: str,
    config_execution_digest: str,
    plan_digest: str,
    context_spec_digest: str,
    context_snapshot_digest: str,
    context_snapshot_binding: dict[str, Any],
    phase: str = "planning",
    workspace: str,
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "id": run_id,
        "schema_version": CURRENT_RUN_SCHEMA_VERSION,
        "revision": 0,
        "status": "running",
        "phase": phase,
        "outcome": None,
        "stop": None,
        "phase_action_id": None,
        "session_replacement_phase_action_id": None,
        "phase_action_domain_committed_id": None,
        "digests": {
            "input": input_digest,
            "output_goal": output_goal_digest,
            "config_contract": config_contract_digest,
            "config_execution": config_execution_digest,
            "plan": plan_digest,
            "context_spec": context_spec_digest,
            "context_snapshot": context_snapshot_digest,
        },
        "context_snapshot_binding": context_snapshot_binding,
        "sessions": initial_structured_sessions(),
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
        validated = validate_run_id(run_id)
        return self._assert_contained(self._root / validated)

    def create_run(
        self,
        run_id: str,
        *,
        plan: Plan | dict[str, Any],
        resolved_config: dict[str, Any],
        input_digest: str,
        output_goal_digest: str,
        context_spec_digest: str,
        context_snapshot_digest: str,
        context_snapshot_binding: dict[str, Any],
        phase: str = "planning",
        production: dict[str, Any] | None = None,
        workspace: str,
        invocation: dict[str, Any],
        run_extras: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a run atomically with its initial ``run_created`` audit event."""

        validated_run_id = validate_run_id(run_id)
        if not input_digest or not output_goal_digest or not context_spec_digest:
            raise PersistenceError(
                "input_digest, output_goal_digest, and context_spec_digest are required"
            )
        if not context_snapshot_digest or not isinstance(context_snapshot_binding, dict):
            raise PersistenceError(
                "context_snapshot_digest and context_snapshot_binding are required"
            )
        validate_context_snapshot_binding(context_snapshot_binding)
        if not workspace or not str(workspace).strip():
            raise PersistenceError("workspace is required")
        if not isinstance(invocation, dict):
            raise PersistenceError("invocation metadata is required")

        final_run_dir = self.run_dir(validated_run_id)
        creation_lock_path = self._assert_contained(
            self._root / f".creating-{validated_run_id}.lock"
        )
        remove_creation_lock = False
        with exclusive_file_lock(creation_lock_path):
            if final_run_dir.exists():
                raise PersistenceError(f"run already exists: {validated_run_id}")

            staging_dir = self._assert_contained(self._root / f".creating-{validated_run_id}")
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

            plan_payload = _canonical_plan_payload(plan)
            config_contract_digest = compute_config_contract_digest(resolved_config)
            config_execution_digest = compute_config_execution_digest(resolved_config)
            plan_digest = compute_plan_digest(plan_payload)
            run_record = new_run_record(
                validated_run_id,
                input_digest=input_digest,
                output_goal_digest=output_goal_digest,
                config_contract_digest=config_contract_digest,
                config_execution_digest=config_execution_digest,
                plan_digest=plan_digest,
                context_spec_digest=context_spec_digest,
                context_snapshot_digest=context_snapshot_digest,
                context_snapshot_binding=context_snapshot_binding,
                phase=phase,
                workspace=workspace,
            )
            if run_extras:
                for key, value in run_extras.items():
                    run_record[key] = value
            if not str(run_record.get("run_kind") or "").strip():
                from top_down_planning.domain.run_kind import default_run_kind_for_phase

                run_record["run_kind"] = default_run_kind_for_phase(phase)

            run_created_event = {
                "type": "run_created",
                "run_id": validated_run_id,
                "revision": run_record["revision"],
                "phase": run_record["phase"],
                "ts": _utc_now(),
            }

            try:
                staging_dir.mkdir(parents=True)
                (staging_dir / "reviews").mkdir()
                (staging_dir / "capabilities").mkdir()
                (staging_dir / "artifacts").mkdir()
                (staging_dir / AGENT_REQUESTS_DIR).mkdir()
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
                atomic_write_text(
                    staging_dir / "events.jsonl",
                    json.dumps(run_created_event, sort_keys=True) + "\n",
                )
                staging_dir.rename(final_run_dir)
                remove_creation_lock = True
            except Exception:
                if staging_dir.exists():
                    shutil.rmtree(staging_dir)
                raise

        if remove_creation_lock and creation_lock_path.exists():
            creation_lock_path.unlink(missing_ok=True)

        return self.load_run(validated_run_id)

    @contextmanager
    def _with_run_commit_lock(self, run_id: str) -> Iterator[str]:
        validated_run_id = validate_run_id(run_id)
        run_dir = self.run_dir(validated_run_id)
        if not run_dir.is_dir():
            raise RunNotFoundError(validated_run_id, "run directory missing", runs_root=self._root)
        lock_path = self._assert_contained(run_dir / ".commit.lock")
        with exclusive_file_lock(lock_path):
            yield validated_run_id

    @contextmanager
    def _with_recovered_run(self, run_id: str) -> Iterator[str]:
        with self._with_run_commit_lock(run_id) as validated_run_id:
            self._recover_incomplete_transactions(validated_run_id)
            yield validated_run_id

    def load_run(self, run_id: str) -> dict[str, Any]:
        with self._with_recovered_run(run_id) as validated_run_id:
            return self._read_run(validated_run_id)

    def load_plan(self, run_id: str) -> dict[str, Any]:
        with self._with_recovered_run(run_id) as validated_run_id:
            return self._read_plan(validated_run_id)

    def load_plan_model(self, run_id: str) -> Plan:
        return Plan.from_dict(self.load_plan(run_id))

    def load_production(self, run_id: str) -> dict[str, Any]:
        with self._with_recovered_run(run_id) as validated_run_id:
            return self._read_production(validated_run_id)

    def commit(self, run_id: str, spec: CommitSpec) -> dict[str, Any]:
        with self._with_recovered_run(run_id) as validated_run_id:
            return self._commit_locked(validated_run_id, self.run_dir(validated_run_id), spec)

    def _commit_locked(
        self,
        validated_run_id: str,
        run_dir: Path,
        spec: CommitSpec,
    ) -> dict[str, Any]:
        if spec.run is not None:
            expected = spec.run_expected_revision
            if expected is None:
                raise PersistenceError("commit with run payload requires run_expected_revision")
            current_revision = int(self._read_run(validated_run_id)["revision"])
            if current_revision != expected:
                raise StoreRevisionConflictError(expected, current_revision)
            next_revision = require_revision_field(spec.run, "run")
            assert_next_revision(expected, next_revision)
            run_payload = dict(spec.run)
            run_payload["revision"] = next_revision
            run_payload["updated_at"] = _utc_now()
            run_payload["sessions"] = sessions_for_persistence(run_payload.get("sessions"))
        else:
            run_payload = None

        if spec.plan is not None:
            expected = spec.plan_expected_revision
            if expected is None:
                raise PersistenceError("commit with plan payload requires plan_expected_revision")
            current_revision = int(self._read_plan(validated_run_id)["revision"])
            if current_revision != expected:
                raise StoreRevisionConflictError(expected, current_revision)
            next_revision = require_revision_field(spec.plan, "plan")
            assert_next_revision(expected, next_revision)
            plan_payload = _canonical_plan_payload(spec.plan)
            plan_payload["revision"] = next_revision
        else:
            plan_payload = None

        if spec.production is not None:
            expected = spec.production_expected_revision
            if expected is None:
                raise PersistenceError(
                    "commit with production payload requires production_expected_revision"
                )
            current_revision = int(self._read_production(validated_run_id)["revision"])
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
            review_payload = review_record_for_persistence(dict(review))
            expected_review_revision = spec.review_expected_revisions.get(validated_review_id)
            if expected_review_revision is not None:
                current_review_revision = self._read_review_revision(
                    validated_run_id,
                    validated_review_id,
                )
                if current_review_revision != int(expected_review_revision):
                    raise StoreRevisionConflictError(
                        int(expected_review_revision),
                        current_review_revision,
                    )
                next_review_revision = int(expected_review_revision) + 1
                review_payload["revision"] = next_review_revision
            review_payloads.append((validated_review_id, review_payload))

        txn_id = uuid.uuid4().hex
        staging_dir = self._assert_contained(run_dir / f".txn-{txn_id}")
        journal_path = staging_dir / "journal.json"
        backups_dir = staging_dir / "backups"
        staging_dir.mkdir()
        backups_dir.mkdir()
        staged_files: list[dict[str, Any]] = []

        journal_events = self._normalize_journal_events(
            txn_id,
            [dict(event) for event in spec.events],
            assign_timestamp=True,
        )

        committed = False
        try:
            if run_payload is not None:
                staged_path = staging_dir / "run.json"
                dest = run_dir / "run.json"
                atomic_write_json(staged_path, run_payload)
                staged_files.append(
                    {
                        "kind": "run",
                        "name": "run.json",
                        "digest": digest_file(staged_path),
                        "had_destination": dest.exists(),
                    }
                )

            if plan_payload is not None:
                staged_path = staging_dir / "plan.json"
                dest = run_dir / "plan.json"
                atomic_write_json(staged_path, plan_payload)
                staged_files.append(
                    {
                        "kind": "plan",
                        "name": "plan.json",
                        "digest": digest_file(staged_path),
                        "had_destination": dest.exists(),
                    }
                )

            if production_payload is not None:
                staged_path = staging_dir / "production.json"
                dest = run_dir / "production.json"
                atomic_write_json(staged_path, production_payload)
                staged_files.append(
                    {
                        "kind": "production",
                        "name": "production.json",
                        "digest": digest_file(staged_path),
                        "had_destination": dest.exists(),
                    }
                )

            if spec.resolved_config is not None:
                staged_path = staging_dir / "resolved-config.yaml"
                dest = run_dir / "resolved-config.yaml"
                atomic_write_text(
                    staged_path,
                    dump_yaml(spec.resolved_config) + "\n",
                )
                staged_files.append(
                    {
                        "kind": "resolved_config",
                        "name": "resolved-config.yaml",
                        "digest": digest_file(staged_path),
                        "had_destination": dest.exists(),
                    }
                )

            if spec.invocation is not None:
                staged_path = staging_dir / "invocation.json"
                dest = run_dir / "invocation.json"
                atomic_write_json(staged_path, spec.invocation)
                staged_files.append(
                    {
                        "kind": "invocation",
                        "name": "invocation.json",
                        "digest": digest_file(staged_path),
                        "had_destination": dest.exists(),
                    }
                )

            for review_id, review_payload in review_payloads:
                staged_name = f"review__{review_id}.json"
                staged_path = staging_dir / staged_name
                reviews_dir = self.reviews_dir(validated_run_id)
                dest = reviews_dir / f"{review_id}.json"
                atomic_write_json(staged_path, review_payload)
                staged_files.append(
                    {
                        "kind": "review",
                        "name": staged_name,
                        "review_id": review_id,
                        "digest": digest_file(staged_path),
                        "had_destination": dest.exists(),
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
                        handle.write(self._serialize_journal_event_line(dict(event)))

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
        binding = payload.get("context_snapshot_binding")
        if binding is not None:
            validate_context_snapshot_binding(binding)
        payload["sessions"] = sessions_for_persistence(payload.get("sessions"))
        next_revision = require_revision_field(payload, "run")
        assert_next_revision(expected_revision, next_revision)
        self.commit(
            run_id,
            CommitSpec(run=payload, run_expected_revision=expected_revision),
        )
        return next_revision

    def save_plan(self, run_id: str, plan: dict[str, Any], expected_revision: int) -> int:
        next_revision = require_revision_field(dict(plan), "plan")
        payload = _canonical_plan_payload(plan)
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
        with self._with_recovered_run(run_id) as validated_run_id:
            path = self._events_path(validated_run_id)
            if not path.exists():
                raise RunNotFoundError(validated_run_id, "events.jsonl missing", runs_root=self._root)
            events = self._load_event_payloads(validated_run_id)
            self._validate_run_created_anchor(validated_run_id, events)
            return events

    def load_resolved_config(self, run_id: str) -> dict[str, Any]:
        with self._with_recovered_run(run_id) as validated_run_id:
            path = self.run_dir(validated_run_id) / "resolved-config.yaml"
            if not path.exists():
                raise RunNotFoundError(
                    validated_run_id,
                    "resolved-config.yaml missing",
                    runs_root=self._root,
                )
            payload = load_yaml(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise PersistenceError("resolved-config.yaml must contain a mapping")
            return payload

    def save_invocation(self, run_id: str, invocation: dict[str, Any]) -> None:
        """Persist CLI invocation metadata under the per-run commit lock.

        Presentation-only metadata is not journaled or digested; callers that need
        snapshot consistency with canonical files should use ``CommitSpec.invocation``.
        """

        with self._with_recovered_run(run_id) as validated_run_id:
            path = self.run_dir(validated_run_id) / "invocation.json"
            atomic_write_json(path, invocation)

    def load_invocation(self, run_id: str) -> dict[str, Any]:
        with self._with_recovered_run(run_id) as validated_run_id:
            path = self.run_dir(validated_run_id) / "invocation.json"
            if not path.exists():
                raise RunNotFoundError(
                    validated_run_id,
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

    def agent_requests_dir(self, run_id: str) -> Path:
        return self._assert_contained(self.run_dir(run_id) / AGENT_REQUESTS_DIR)

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
        session_instance_id: str | None = None,
        generation: int | None = None,
    ) -> tuple[str, dict[str, Any], str]:
        capability_id, record, raw_secret = new_capability_record(
            run_id=run_id,
            role=role,
            phase=phase,
            allowed_ops=allowed_ops,
            session_id=session_id,
            session_kind=session_kind,
            loop_id=loop_id,
            session_instance_id=session_instance_id,
            generation=generation,
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
        try:
            exclusive_create_bytes(path, data)
        except FileExistsError as exc:
            raise PersistenceError(
                f"artifact snapshot already exists: {snapshot_id}/{filename}"
            ) from exc
        return str(
            Path("artifacts")
            / validate_store_id(snapshot_id, label="snapshot_id")
            / validate_store_id(filename, label="artifact_filename")
        )

    def save_review(
        self,
        run_id: str,
        review: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> None:
        review_id = review.get("id")
        if not review_id:
            raise PersistenceError("review record requires id")
        validated_review_id = validate_store_id(str(review_id), label="review_id")
        review_expected: dict[str, int] = {}
        if expected_revision is not None:
            review_expected[validated_review_id] = int(expected_revision)
        self.commit(
            run_id,
            CommitSpec(
                reviews=[review_record_for_persistence(dict(review))],
                review_expected_revisions=review_expected,
            ),
        )

    def load_review(self, run_id: str, review_id: str) -> dict[str, Any]:
        validated_review_id = validate_store_id(review_id, label="review_id")
        with self._with_recovered_run(run_id) as validated_run_id:
            path = self.reviews_dir(validated_run_id) / f"{validated_review_id}.json"
            if not path.exists():
                raise RunNotFoundError(
                    validated_run_id,
                    f"review {validated_review_id} missing",
                    runs_root=self._root,
                )
            return normalize_review_record_for_runtime(self._read_json(path))

    def list_reviews(self, run_id: str) -> list[dict[str, Any]]:
        with self._with_recovered_run(run_id) as validated_run_id:
            reviews_dir = self.reviews_dir(validated_run_id)
            if not reviews_dir.is_dir():
                return []
            reviews: list[dict[str, Any]] = []
            for path in sorted(reviews_dir.glob("*.json")):
                reviews.append(normalize_review_record_for_runtime(self._read_json(path)))
            return reviews

    def _recover_incomplete_transactions(self, run_id: str) -> None:
        """Recover journaled transactions. Caller must hold the per-run commit lock."""
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
        txn_id = staging_dir.name.removeprefix(".txn-")
        if not txn_id:
            raise TransactionRecoveryError(
                "invalid transaction directory name",
                run_id=run_id,
                txn_id="unknown",
            )

        journal_path = staging_dir / "journal.json"
        if not journal_path.is_file():
            raise TransactionRecoveryError(
                "transaction journal missing",
                run_id=run_id,
                txn_id=txn_id,
            )

        journal = self._read_transaction_journal(journal_path, run_id, txn_id)
        parsed = parse_recovery_journal(journal, run_id=run_id, expected_txn_id=txn_id)
        status = parsed.status
        if status not in _KNOWN_TXN_STATUSES:
            raise TransactionRecoveryError(
                f"unknown transaction status: {status}",
                run_id=run_id,
                txn_id=txn_id,
            )
        staged_files = [journal_file_entry_as_dict(entry) for entry in parsed.files]
        journal_events = parsed.events
        backups_dir = staging_dir / "backups"
        replaced = parsed.replaced

        for name in parsed.backups:
            backup_path = backups_dir / name
            if not backup_path.is_file():
                raise TransactionRecoveryError(
                    f"transaction journal backup missing on disk: {name}",
                    run_id=run_id,
                    txn_id=txn_id,
                )

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
            self._require_committed_staged_files(
                run_dir,
                staged_files,
                replaced,
                run_id=run_id,
                txn_id=txn_id,
            )
            if txn_id and journal_events:
                self._ensure_events_appended(run_id, txn_id, journal_events)
            shutil.rmtree(staging_dir)
            return

        if status == "committed":
            self._require_committed_staged_files(
                run_dir,
                staged_files,
                replaced,
                run_id=run_id,
                txn_id=txn_id,
            )
            if txn_id and journal_events:
                self._ensure_events_appended(run_id, txn_id, journal_events)
            shutil.rmtree(staging_dir)
            return

    def _validate_run_created_anchor(
        self,
        run_id: str,
        events: list[dict[str, Any]],
    ) -> None:
        if not events:
            raise PersistenceError("events.jsonl must contain a run_created event")
        first = events[0]
        if first.get("type") != "run_created":
            raise PersistenceError("events.jsonl must begin with run_created")
        if str(first.get("run_id") or "") != run_id:
            raise PersistenceError("run_created run_id does not match run")

    def _read_transaction_journal(
        self,
        journal_path: Path,
        run_id: str,
        expected_txn_id: str,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(journal_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TransactionRecoveryError(
                f"transaction journal is malformed: {exc}",
                run_id=run_id,
                txn_id=expected_txn_id,
            ) from exc
        if not isinstance(payload, dict):
            raise TransactionRecoveryError(
                "transaction journal must be a mapping",
                run_id=run_id,
                txn_id=expected_txn_id,
            )
        journal_txn_id = str(payload.get("txn_id") or "").strip()
        if not journal_txn_id:
            raise TransactionRecoveryError(
                "transaction journal missing txn_id",
                run_id=run_id,
                txn_id=expected_txn_id,
            )
        if journal_txn_id != expected_txn_id:
            raise TransactionRecoveryError(
                "transaction journal txn_id mismatch with staging directory",
                run_id=run_id,
                txn_id=expected_txn_id,
            )
        return payload

    def _normalize_journal_events(
        self,
        txn_id: str,
        journal_events: list[dict[str, Any]],
        *,
        assign_timestamp: bool = False,
    ) -> list[dict[str, Any]]:
        event_count = len(journal_events)
        normalized: list[dict[str, Any]] = []
        for event_index, event in enumerate(journal_events):
            payload = dict(event)
            payload["txn_id"] = txn_id
            payload["event_index"] = event_index
            payload["event_count"] = event_count
            if assign_timestamp or "ts" not in payload:
                payload["ts"] = _utc_now()
            normalized.append(payload)
        return normalized

    @staticmethod
    def _serialize_journal_event_line(payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True) + "\n"

    def _require_journaled_event_fields(self, payload: dict[str, Any]) -> None:
        txn_id = payload.get("txn_id")
        has_txn = txn_id is not None and str(txn_id).strip() != ""
        has_index = "event_index" in payload
        has_count = "event_count" in payload

        if not has_txn and not has_index and not has_count:
            return

        if not has_txn or not has_index or not has_count:
            missing: list[str] = []
            if not has_txn:
                missing.append("txn_id")
            if not has_index:
                missing.append("event_index")
            if not has_count:
                missing.append("event_count")
            raise PersistenceError(
                "events.jsonl journaled event missing required fields: "
                + ", ".join(missing)
            )

        event_index = payload["event_index"]
        event_count = payload["event_count"]
        if not isinstance(event_index, int) or isinstance(event_index, bool):
            raise PersistenceError("events.jsonl event_index must be an integer")
        if not isinstance(event_count, int) or isinstance(event_count, bool):
            raise PersistenceError("events.jsonl event_count must be an integer")
        if event_count <= 0:
            raise PersistenceError("events.jsonl event_count must be positive")
        if event_index < 0 or event_index >= event_count:
            raise PersistenceError(
                "events.jsonl event_index must satisfy 0 <= event_index < event_count"
            )

    def _validate_event_log_integrity(self, events: list[dict[str, Any]]) -> None:
        txn_indices: dict[str, list[int]] = {}
        txn_counts: dict[str, int] = {}
        seen: set[tuple[str, int]] = set()

        for payload in events:
            txn_id = payload.get("txn_id")
            if txn_id is None or not str(txn_id).strip():
                continue
            normalized_txn_id = str(txn_id)
            event_index = int(payload["event_index"])
            event_count = int(payload["event_count"])
            key = (normalized_txn_id, event_index)
            if key in seen:
                raise PersistenceError(
                    f"duplicate journaled event {normalized_txn_id!r} index {event_index}"
                )
            seen.add(key)

            previous_count = txn_counts.get(normalized_txn_id)
            if previous_count is not None and previous_count != event_count:
                raise PersistenceError(
                    f"events.jsonl txn_id {normalized_txn_id!r} has inconsistent event_count"
                )
            txn_counts[normalized_txn_id] = event_count
            txn_indices.setdefault(normalized_txn_id, []).append(event_index)

        for normalized_txn_id, ordered in txn_indices.items():
            event_count = txn_counts[normalized_txn_id]
            expected = list(range(event_count))
            if ordered == expected:
                continue
            if set(ordered) == set(expected):
                raise PersistenceError(
                    f"journaled events for txn_id {normalized_txn_id!r} are out of physical order"
                )
            raise PersistenceError(
                f"incomplete journaled event set for txn_id {normalized_txn_id!r}"
            )

    def _parse_events_text(
        self,
        text: str,
        events_path: Path,
        *,
        ignore_malformed_trailing: bool = False,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if not text:
            return events

        if text.endswith("\n"):
            body_lines = text.splitlines()
            trailing_line: str | None = None
        else:
            if "\n" not in text:
                body_lines: list[str] = []
                trailing_line = text
            else:
                body, trailing_line = text.rsplit("\n", 1)
                body_lines = body.splitlines() if body else []

        for line in body_lines:
            if not line.strip():
                continue
            events.append(self._parse_event_line(line, events_path))

        if trailing_line is not None and trailing_line.strip():
            try:
                events.append(self._parse_event_line(trailing_line, events_path))
            except PersistenceError:
                if not ignore_malformed_trailing:
                    raise

        return events

    def _parse_event_line(self, line: str, events_path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PersistenceError(
                f"failed to load malformed events.jsonl line in {events_path}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise PersistenceError(
                f"events.jsonl line in {events_path} must be a JSON object"
            )
        self._require_journaled_event_fields(payload)
        return payload

    def _repair_recoverable_trailing_fragment(
        self,
        run_id: str,
        txn_id: str,
        journal_events: list[dict[str, Any]],
    ) -> None:
        normalized_events = self._normalize_journal_events(txn_id, journal_events)
        events_path = self._events_path(run_id)
        if not events_path.is_file():
            return
        text = events_path.read_text(encoding="utf-8")
        if not text or text.endswith("\n"):
            return
        trailing = text.rsplit("\n", 1)[-1]
        if trailing.strip():
            try:
                json.loads(trailing)
                return
            except json.JSONDecodeError:
                pass

        event_count = int(normalized_events[0]["event_count"]) if normalized_events else 0
        existing_indices = (
            self._existing_transaction_event_indices(
                run_id,
                txn_id,
                expected_event_count=event_count,
            )
            if normalized_events
            else set()
        )
        next_event: dict[str, Any] | None = None
        for event in normalized_events:
            if int(event["event_index"]) not in existing_indices:
                next_event = event
                break

        if next_event is None:
            if trailing.strip():
                raise TransactionRecoveryError(
                    "unrelated trailing event fragment in events.jsonl",
                    run_id=run_id,
                    txn_id=txn_id,
                )
            return

        expected_line = json.dumps(next_event, sort_keys=True)
        if trailing and not expected_line.startswith(trailing):
            raise TransactionRecoveryError(
                "unrelated trailing event fragment in events.jsonl",
                run_id=run_id,
                txn_id=txn_id,
            )

        last_newline = text.rfind("\n")
        repaired = "" if last_newline == -1 else text[: last_newline + 1]
        self._atomically_publish_events_text(events_path, repaired)

    def _atomically_publish_events_text(self, events_path: Path, text: str) -> None:
        tmp_path = events_path.with_name(
            f".{events_path.name}.repair-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
        try:
            tmp_path.write_text(text, encoding="utf-8")
            if tmp_path.read_text(encoding="utf-8") != text:
                raise PersistenceError("temporary events repair write incomplete")
            tmp_path.replace(events_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _load_event_payloads(
        self,
        run_id: str,
        *,
        validate_integrity: bool = True,
        ignore_malformed_trailing: bool = False,
    ) -> list[dict[str, Any]]:
        events_path = self._events_path(run_id)
        if not events_path.is_file():
            return []
        text = events_path.read_text(encoding="utf-8")
        events = self._parse_events_text(
            text,
            events_path,
            ignore_malformed_trailing=ignore_malformed_trailing,
        )
        if validate_integrity:
            self._validate_event_log_integrity(events)
        return events

    def _existing_transaction_event_indices(
        self,
        run_id: str,
        txn_id: str,
        *,
        expected_event_count: int,
    ) -> set[int]:
        ordered_indices: list[int] = []
        for payload in self._load_event_payloads(
            run_id,
            validate_integrity=False,
            ignore_malformed_trailing=True,
        ):
            if str(payload.get("txn_id") or "") != txn_id:
                continue
            event_count = int(payload["event_count"])
            if event_count != expected_event_count:
                raise PersistenceError(
                    f"events.jsonl txn_id {txn_id!r} has inconsistent event_count"
                )
            ordered_indices.append(int(payload["event_index"]))

        if ordered_indices and ordered_indices != list(range(len(ordered_indices))):
            raise TransactionRecoveryError(
                "journaled events for transaction are out of order or gapped",
                run_id=run_id,
                txn_id=txn_id,
            )
        return set(ordered_indices)

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
        normalized_events = self._normalize_journal_events(txn_id, journal_events)
        if not normalized_events:
            return

        self._repair_recoverable_trailing_fragment(run_id, txn_id, journal_events)

        event_count = int(normalized_events[0]["event_count"])
        existing_indices = self._existing_transaction_event_indices(
            run_id,
            txn_id,
            expected_event_count=event_count,
        )
        if existing_indices >= set(range(event_count)):
            return

        events_path = self._events_path(run_id)
        missing_events = [
            event
            for event in normalized_events
            if int(event["event_index"]) not in existing_indices
        ]
        missing_events.sort(key=lambda event: int(event["event_index"]))

        with events_path.open("a", encoding="utf-8") as handle:
            for event in missing_events:
                handle.write(self._serialize_journal_event_line(dict(event)))

    def _require_committed_staged_files(
        self,
        run_dir: Path,
        staged_files: list[dict[str, Any]],
        replaced: list[str],
        *,
        run_id: str,
        txn_id: str,
    ) -> None:
        all_names = {str(entry.get("name") or "") for entry in staged_files}
        replaced_names = {str(name) for name in replaced}
        if replaced_names != all_names:
            raise TransactionRecoveryError(
                "transaction journal replaced must include every staged file",
                run_id=run_id,
                txn_id=txn_id,
            )
        if staged_files and not self._verify_replaced_files_match_staged(
            run_dir,
            staged_files,
            replaced,
        ):
            raise TransactionRecoveryError(
                "canonical destination digest mismatch for staged transaction file",
                run_id=run_id,
                txn_id=txn_id,
            )

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

    def _read_run(self, run_id: str) -> dict[str, Any]:
        # Schema-version gate before any nested run-field interpretation (§3).
        payload = self._read_json(self._run_path(run_id))
        validate_run_schema_version(payload)
        validate_run_digests(payload)
        binding = payload.get("context_snapshot_binding")
        if binding is not None:
            validate_context_snapshot_binding(binding)
        try:
            validate_run_lifecycle_invariants(payload)
            validate_session_recovery_fields(payload)
        except RunLifecycleError as exc:
            raise PersistenceError(str(exc)) from exc
        payload = dict(payload)
        payload["sessions"] = normalize_sessions_for_runtime(payload.get("sessions"))
        return payload

    def _plan_path(self, run_id: str) -> Path:
        path = self.run_dir(run_id) / "plan.json"
        self._require_file(path, run_id)
        return path

    def _read_plan(self, run_id: str) -> dict[str, Any]:
        payload = self._read_json(self._plan_path(run_id))
        validate_plan_schema_version(payload)
        return payload

    def _production_path(self, run_id: str) -> Path:
        path = self.run_dir(run_id) / "production.json"
        self._require_file(path, run_id)
        return path

    def _read_production(self, run_id: str) -> dict[str, Any]:
        return self._read_json(self._production_path(run_id))

    def _read_review_revision(self, run_id: str, review_id: str) -> int:
        path = self.reviews_dir(run_id) / f"{review_id}.json"
        if not path.exists():
            return 0
        return int(self._read_json(path).get("revision") or 0)

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
