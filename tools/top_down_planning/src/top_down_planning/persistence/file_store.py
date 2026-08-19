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
    atomic_write_bytes,
    digest_bytes,
    digest_file,
    dump_yaml,
    exclusive_create_bytes,
    exclusive_file_lock,
    load_yaml,
    parse_revision_value,
    require_revision_field,
)
from top_down_planning.persistence.capabilities import new_capability_record

AGENT_REQUESTS_DIR = "agent-requests"
from top_down_planning.persistence.commit import (
    CommitSpec,
    StoreAuthorizationConflictError,
)
from top_down_planning.persistence.snapshot import CanonicalRunSnapshot
from top_down_planning.persistence.journal_schema import (
    KNOWN_TXN_STATUSES,
    ParsedRecoveryJournal,
    journal_file_entry_as_dict,
    parse_recovery_journal,
)
from top_down_planning.persistence.transaction_inspect import (
    journal_events_suffix_bytes,
    replaced_destinations_match,
    require_committed_destinations,
    validate_run_transactions_for_recovery,
    verify_events_append_recoverable,
)
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
    compute_plan_digest,
)
from top_down_planning.persistence.path_containment import (
    lexical_run_dir,
    lexical_run_owned_path,
    lexical_store_owned_path,
    lexical_txn_owned_path,
    reject_symlink_path,
    require_non_symlink_run_boundary,
    validate_journal_basename,
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
)
from top_down_planning.config.binding_validation import validate_context_snapshot_binding
from top_down_planning.persistence.persisted_validation import (
    canonicalize_persisted_plan,
    canonicalize_persisted_review,
    parse_canonical_events_text,
    reject_protected_run_extras_keys,
    validate_canonical_run,
    validate_event_log_integrity,
    validate_persisted_invocation,
    validate_persisted_production,
    validate_persisted_review_binding,
    validate_persisted_run,
    validate_run_created_anchor,
)
from top_down_planning.persistence.snapshot_bindings import (
    bind_run_digests_for_config_update,
    bind_run_digests_for_plan_update,
    bind_run_digests_for_production_update,
    validate_context_snapshot_transition,
    validate_snapshot_digest_bindings,
)
from top_down_planning.persistence.session_bindings import (
    initial_structured_sessions,
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
        lexical = lexical_run_dir(self._root, validated)
        if lexical.is_dir():
            require_non_symlink_run_boundary(lexical)
        return lexical

    def _assert_run_contained(self, run_dir: Path, path: Path) -> Path:
        return lexical_run_owned_path(run_dir, path)

    def _assert_contained(self, path: Path) -> Path:
        return lexical_store_owned_path(self._root, path)

    def _owned_run_file(self, run_id: str, name: str) -> Path:
        run_dir = self.run_dir(run_id)
        return lexical_run_owned_path(run_dir, run_dir / name)

    def _review_record_path(self, run_id: str, review_id: str) -> Path:
        validated_review_id = validate_store_id(review_id, label="review_id")
        run_dir = self.run_dir(run_id)
        return lexical_run_owned_path(
            run_dir,
            run_dir / "reviews" / f"{validated_review_id}.json",
        )

    def _capability_record_path(self, run_id: str, capability_id: str) -> Path:
        validated_id = validate_store_id(capability_id, label="capability_id")
        run_dir = self.run_dir(run_id)
        return lexical_run_owned_path(
            run_dir,
            run_dir / "capabilities" / f"{validated_id}.json",
        )

    def _txn_journal_path(self, txn_dir: Path) -> Path:
        return lexical_txn_owned_path(txn_dir, txn_dir / "journal.json")

    def _txn_backups_dir(self, txn_dir: Path) -> Path:
        backups_dir = lexical_txn_owned_path(txn_dir, txn_dir / "backups")
        if backups_dir.is_symlink():
            raise PersistenceError("transaction backups directory must not be a symlink")
        return backups_dir

    def _txn_backup_path(self, txn_dir: Path, name: str) -> Path:
        validated_name = validate_journal_basename(name, label="backup name")
        backups_dir = self._txn_backups_dir(txn_dir)
        return lexical_txn_owned_path(txn_dir, backups_dir / validated_name)

    def _txn_staged_path(self, txn_dir: Path, name: str) -> Path:
        validated_name = validate_journal_basename(name, label="staged file name")
        return lexical_txn_owned_path(txn_dir, txn_dir / validated_name)

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
        invocation = validate_persisted_invocation(invocation)

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
                reject_protected_run_extras_keys(run_extras)
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

            production_payload = (
                production if production is not None else dict(_EMPTY_PRODUCTION)
            )
            from top_down_planning.domain.production import live_output_evidence_entries

            if live_output_evidence_entries(production_payload):
                raise PersistenceError(
                    "create_run cannot persist live output evidence; "
                    "production must start without captured snapshots"
                )
            production_payload = validate_persisted_production(
                production_payload,
                plan=plan_payload,
            )
            workspace_path = Path(str(workspace)).resolve()
            from top_down_planning.persistence.snapshot_bindings import (
                validate_create_run_context_binding,
            )

            validate_create_run_context_binding(
                resolved_config=resolved_config,
                workspace=workspace_path,
                context_snapshot_binding=context_snapshot_binding,
                context_snapshot_digest=context_snapshot_digest,
            )
            validate_snapshot_digest_bindings(
                run_record,
                plan=plan_payload,
                production=production_payload,
                resolved_config=resolved_config,
                workspace=workspace_path,
            )

            canonical_run = None
            try:
                staging_dir.mkdir(parents=True)
                (staging_dir / "reviews").mkdir()
                (staging_dir / "capabilities").mkdir()
                (staging_dir / "artifacts").mkdir()
                (staging_dir / AGENT_REQUESTS_DIR).mkdir()
                canonical_run = validate_canonical_run(validated_run_id, run_record)
                atomic_write_text(
                    staging_dir / "resolved-config.yaml",
                    dump_yaml(resolved_config) + "\n",
                )
                atomic_write_json(staging_dir / "run.json", canonical_run)
                atomic_write_json(staging_dir / "plan.json", plan_payload)
                atomic_write_json(
                    staging_dir / "production.json",
                    production_payload,
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

        if canonical_run is None:
            raise PersistenceError(
                f"create_run did not publish a canonical run: {validated_run_id}"
            )
        return dict(canonical_run)

    @contextmanager
    def _with_run_commit_lock(self, run_id: str) -> Iterator[str]:
        validated_run_id = validate_run_id(run_id)
        run_dir = self.run_dir(validated_run_id)
        if not run_dir.is_dir():
            raise RunNotFoundError(validated_run_id, "run directory missing", runs_root=self._root)
        lock_path = self._assert_run_contained(run_dir, run_dir / ".commit.lock")
        with exclusive_file_lock(lock_path):
            self._verify_canonical_run_identity(validated_run_id, run_dir)
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

    def load_canonical_snapshot(self, run_id: str) -> CanonicalRunSnapshot:
        with self._with_recovered_run(run_id) as validated_run_id:
            return CanonicalRunSnapshot(
                run=self._read_run(validated_run_id),
                plan=self._read_plan(validated_run_id),
                production=self._read_production(validated_run_id),
                reviews=self._read_reviews(validated_run_id),
                resolved_config=self._read_resolved_config(validated_run_id),
            )

    def commit(self, run_id: str, spec: CommitSpec) -> dict[str, Any]:
        with self._with_recovered_run(run_id) as validated_run_id:
            return self._commit_locked(validated_run_id, self.run_dir(validated_run_id), spec)

    def recover_incomplete_transactions(self, run_id: str) -> None:
        """Recover abandoned journals under the commit lock without extra canonical reads."""

        with self._with_run_commit_lock(run_id) as validated_run_id:
            self._recover_incomplete_transactions(validated_run_id)

    def _commit_locked(
        self,
        validated_run_id: str,
        run_dir: Path,
        spec: CommitSpec,
    ) -> dict[str, Any]:
        if spec.run is not None:
            expected_raw = spec.run_expected_revision
            if expected_raw is None:
                raise PersistenceError("commit with run payload requires run_expected_revision")
            expected = parse_revision_value(expected_raw, "run")
            current_revision = parse_revision_value(
                self._read_run(validated_run_id)["revision"],
                "run",
            )
            if current_revision != expected:
                raise StoreRevisionConflictError(expected, current_revision)
            next_revision = require_revision_field(spec.run, "run")
            assert_next_revision(expected, next_revision)
            run_payload = dict(spec.run)
            run_payload["revision"] = next_revision
            run_payload["updated_at"] = _utc_now()
            if "sessions" in run_payload:
                run_payload["sessions"] = sessions_for_persistence(run_payload["sessions"])
            else:
                run_payload["sessions"] = self._read_run(validated_run_id)["sessions"]
        else:
            run_payload = None

        current_run = self._read_run(validated_run_id)
        if spec.run is None and spec.run_expected_revision is not None:
            expected = parse_revision_value(spec.run_expected_revision, "run")
            current_revision = parse_revision_value(current_run["revision"], "run")
            if current_revision != expected:
                raise StoreRevisionConflictError(expected, current_revision)

        if spec.authorized_phase is not None:
            current_phase = str(current_run.get("phase") or "")
            if current_phase != spec.authorized_phase:
                raise StoreAuthorizationConflictError(
                    f"authorized phase {spec.authorized_phase!r} does not match "
                    f"run phase {current_phase!r}"
                )

        if spec.authorized_capability_id is not None:
            capability = self._read_capability_record(
                validated_run_id,
                spec.authorized_capability_id,
            )
            if capability.get("revoked") is True:
                raise StoreAuthorizationConflictError("capability token has been revoked")
            record_phase = str(capability.get("phase") or "")
            current_phase = str(current_run.get("phase") or "")
            if record_phase != current_phase:
                raise StoreAuthorizationConflictError(
                    f"capability token phase {record_phase!r} does not match "
                    f"run phase {current_phase!r}"
                )

        if spec.plan is not None:
            expected_raw = spec.plan_expected_revision
            if expected_raw is None:
                raise PersistenceError("commit with plan payload requires plan_expected_revision")
            expected = parse_revision_value(expected_raw, "plan")
            current_revision = parse_revision_value(
                self._read_plan(validated_run_id)["revision"],
                "plan",
            )
            if current_revision != expected:
                raise StoreRevisionConflictError(expected, current_revision)
            next_revision = require_revision_field(spec.plan, "plan")
            assert_next_revision(expected, next_revision)
            plan_payload = _canonical_plan_payload(spec.plan)
            plan_payload["revision"] = next_revision
        else:
            plan_payload = None

        if spec.production is not None:
            expected_raw = spec.production_expected_revision
            if expected_raw is None:
                raise PersistenceError(
                    "commit with production payload requires production_expected_revision"
                )
            expected = parse_revision_value(expected_raw, "production")
            current_revision = parse_revision_value(
                self._read_production(validated_run_id)["revision"],
                "production",
            )
            if current_revision != expected:
                raise StoreRevisionConflictError(expected, current_revision)
            next_revision = require_revision_field(spec.production, "production")
            assert_next_revision(expected, next_revision)
            production_payload = dict(spec.production)
            production_payload["revision"] = next_revision
        else:
            production_payload = None

        resolved_config_payload = spec.resolved_config

        auto_run_patch: dict[str, Any] | None = None
        if run_payload is None and (
            plan_payload is not None
            or production_payload is not None
            or resolved_config_payload is not None
        ):
            run_expected = parse_revision_value(current_run["revision"], "run")
            if spec.run_expected_revision is not None:
                run_expected = parse_revision_value(spec.run_expected_revision, "run")
            auto_run_patch = {
                **current_run,
                "revision": run_expected + 1,
                "updated_at": _utc_now(),
            }

        if plan_payload is not None and run_payload is None:
            assert auto_run_patch is not None
            auto_run_patch = bind_run_digests_for_plan_update(
                auto_run_patch,
                plan_payload,
            )

        if production_payload is not None and run_payload is None:
            assert auto_run_patch is not None
            auto_run_patch = bind_run_digests_for_production_update(
                auto_run_patch,
                production_payload,
            )

        if resolved_config_payload is not None and run_payload is None:
            assert auto_run_patch is not None
            workspace_path = Path(str(current_run.get("workspace") or "")).resolve()
            from top_down_planning.config.context_digests import context_spec_diff_is_model_only

            old_config = self._read_resolved_config(validated_run_id)
            if not context_spec_diff_is_model_only(
                old_config,
                resolved_config_payload,
                workspace=workspace_path,
            ):
                raise PersistenceError(
                    "resolved-config structural context change requires explicit "
                    "run binding transition"
                )
            auto_run_patch = bind_run_digests_for_config_update(
                auto_run_patch,
                resolved_config_payload,
                workspace=workspace_path,
            )

        if auto_run_patch is not None and run_payload is None:
            run_payload = validate_canonical_run(validated_run_id, auto_run_patch)

        review_payloads: list[tuple[str, dict[str, Any]]] = []
        for review in spec.reviews:
            review_id = review.get("id")
            if not review_id:
                raise PersistenceError("review record requires id")
            validated_review_id = validate_store_id(str(review_id), label="review_id")
            review_path = self.reviews_dir(validated_run_id) / f"{validated_review_id}.json"
            review_exists = review_path.is_file()
            expected_review_revision = spec.review_expected_revisions.get(validated_review_id)
            if expected_review_revision is None:
                if review_exists:
                    current_review_revision = self._read_review_revision(
                        validated_run_id,
                        validated_review_id,
                    )
                    raise StoreRevisionConflictError(0, current_review_revision)
                review_payload = canonicalize_persisted_review(
                    validated_review_id,
                    dict(review),
                )
            else:
                expected_parsed = parse_revision_value(
                    expected_review_revision,
                    "review",
                )
                current_review_revision = self._read_review_revision(
                    validated_run_id,
                    validated_review_id,
                )
                if current_review_revision != expected_parsed:
                    raise StoreRevisionConflictError(
                        expected_parsed,
                        current_review_revision,
                    )
                review_payload = canonicalize_persisted_review(
                    validated_review_id,
                    dict(review),
                )
                review_payload["revision"] = expected_parsed + 1
            review_payloads.append((validated_review_id, review_payload))

        prospective_run = run_payload if run_payload is not None else current_run
        prospective_plan = (
            plan_payload
            if plan_payload is not None
            else self._read_plan(validated_run_id)
        )
        prospective_production = (
            production_payload
            if production_payload is not None
            else self._read_production(validated_run_id)
        )
        prospective_config = (
            resolved_config_payload
            if resolved_config_payload is not None
            else self._read_resolved_config(validated_run_id)
        )
        if (
            run_payload is not None
            or plan_payload is not None
            or production_payload is not None
            or resolved_config_payload is not None
        ):
            workspace = Path(str(prospective_run.get("workspace") or "")).resolve()
            from top_down_planning.persistence.evidence_integrity import (
                verify_persisted_production_evidence_snapshots,
            )
            from top_down_planning.persistence.snapshot_bindings import (
                context_snapshot_will_change,
            )

            try:
                prospective_production = validate_persisted_production(
                    prospective_production,
                    plan=prospective_plan,
                )
            except ValueError as exc:
                raise PersistenceError(f"production payload is invalid: {exc}") from exc
            if production_payload is not None:
                production_payload = prospective_production
            if (
                production_payload is not None
                or context_snapshot_will_change(current_run, prospective_run)
            ):
                verify_persisted_production_evidence_snapshots(
                    self,
                    validated_run_id,
                    prospective_production,
                    staged_artifacts=spec.artifacts,
                )
            validate_context_snapshot_transition(
                current_run,
                prospective_run,
                self._read_resolved_config(validated_run_id),
                prospective_config,
                workspace=workspace,
                production=prospective_production,
            )
            validate_snapshot_digest_bindings(
                prospective_run,
                plan=prospective_plan,
                production=prospective_production,
                resolved_config=prospective_config,
                workspace=workspace,
            )

        if run_payload is not None:
            run_payload = validate_canonical_run(validated_run_id, run_payload)
        if plan_payload is not None:
            plan_payload = canonicalize_persisted_plan(plan_payload)

        txn_id = uuid.uuid4().hex
        journal_events = self._normalize_journal_events(
            txn_id,
            [dict(event) for event in spec.events],
            assign_timestamp=True,
        )

        if journal_events:
            self._ensure_events_file_append_boundary(validated_run_id)

        events_base_size = 0
        events_base_digest = digest_bytes(b"")
        if journal_events:
            events_path = self._events_path(validated_run_id)
            events_bytes = events_path.read_bytes() if events_path.is_file() else b""
            events_base_size = len(events_bytes)
            events_base_digest = digest_bytes(events_bytes)

        stage_dir = self._assert_run_contained(run_dir, run_dir / f".stage-{txn_id}")
        journal_path = stage_dir / "journal.json"
        backups_dir = stage_dir / "backups"
        staged_files: list[dict[str, Any]] = []

        published = False
        committed = False
        txn_dir: Path | None = None
        try:
            stage_dir.mkdir()
            backups_dir.mkdir()
            for artifact in spec.artifacts:
                snapshot_id = validate_store_id(artifact.snapshot_id, label="snapshot_id")
                filename = validate_store_id(artifact.filename, label="artifact_filename")
                staged_name = f"artifact__{snapshot_id}__{filename}"
                staged_path = stage_dir / staged_name
                dest = self.artifacts_dir(validated_run_id) / snapshot_id / filename
                if dest.exists():
                    raise PersistenceError(
                        f"artifact snapshot already exists: {snapshot_id}/{filename}"
                    )
                atomic_write_bytes(staged_path, artifact.data)
                staged_files.append(
                    {
                        "kind": "artifact",
                        "name": staged_name,
                        "snapshot_id": snapshot_id,
                        "filename": filename,
                        "digest": digest_file(staged_path),
                        "had_destination": False,
                    }
                )

            if run_payload is not None:
                staged_path = stage_dir / "run.json"
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
                staged_path = stage_dir / "plan.json"
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
                staged_path = stage_dir / "production.json"
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

            if resolved_config_payload is not None:
                staged_path = stage_dir / "resolved-config.yaml"
                dest = run_dir / "resolved-config.yaml"
                atomic_write_text(
                    staged_path,
                    dump_yaml(resolved_config_payload) + "\n",
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
                invocation_payload = validate_persisted_invocation(spec.invocation)
                staged_path = stage_dir / "invocation.json"
                dest = run_dir / "invocation.json"
                atomic_write_json(staged_path, invocation_payload)
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
                staged_path = stage_dir / staged_name
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
                "events_base_size": events_base_size,
                "events_base_digest": events_base_digest,
            }
            atomic_write_json(journal_path, journal)

            txn_dir = self._assert_run_contained(run_dir, run_dir / f".txn-{txn_id}")
            stage_dir.rename(txn_dir)
            published = True
            journal_path = self._txn_journal_path(txn_dir)
            self._txn_backups_dir(txn_dir)

            journal["status"] = "replacing"
            atomic_write_json(journal_path, journal)

            for entry in staged_files:
                staged_path = self._txn_staged_path(txn_dir, entry["name"])
                dest = self._destination_for_staged_entry(run_dir, entry)
                dest.parent.mkdir(parents=True, exist_ok=True)
                self._assert_run_contained(run_dir, dest)
                if dest.exists():
                    if entry["kind"] == "artifact":
                        raise PersistenceError(
                            "artifact snapshot already exists: "
                            f"{entry.get('snapshot_id')}/{entry.get('filename')}"
                        )
                    backup_path = self._txn_backup_path(txn_dir, entry["name"])
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
                with events_path.open("ab") as handle:
                    handle.write(self._journal_events_suffix_bytes(journal_events))

            journal["status"] = "committed"
            atomic_write_json(journal_path, journal)
            committed = True
        finally:
            if committed and txn_dir is not None:
                self._retire_transaction_dir(run_dir, txn_dir)
            elif not published and stage_dir.exists():
                shutil.rmtree(stage_dir)

        result: dict[str, Any] = {"ok": True}
        if run_payload is not None:
            result["run_revision"] = int(run_payload["revision"])
        if plan_payload is not None:
            result["plan_revision"] = int(plan_payload["revision"])
        if production_payload is not None:
            result["production_revision"] = int(production_payload["revision"])
        return result

    def save_run(self, run_id: str, run: dict[str, Any], expected_revision: int) -> int:
        expected = parse_revision_value(expected_revision, "run")
        payload = dict(run)
        binding = payload.get("context_snapshot_binding")
        if binding is not None:
            validate_context_snapshot_binding(binding)
        if "sessions" in payload:
            payload["sessions"] = sessions_for_persistence(payload["sessions"])
        next_revision = require_revision_field(payload, "run")
        assert_next_revision(expected, next_revision)
        self.commit(
            run_id,
            CommitSpec(run=payload, run_expected_revision=expected),
        )
        return next_revision

    def save_plan(self, run_id: str, plan: dict[str, Any], expected_revision: int) -> int:
        expected = parse_revision_value(expected_revision, "plan")
        next_revision = require_revision_field(dict(plan), "plan")
        payload = _canonical_plan_payload(plan)
        assert_next_revision(expected, next_revision)
        self.commit(
            run_id,
            CommitSpec(plan=payload, plan_expected_revision=expected),
        )
        return next_revision

    def save_plan_model(self, run_id: str, plan: Plan, expected_revision: int) -> int:
        return self.save_plan(run_id, plan.to_dict(), expected_revision)

    def save_production(
        self, run_id: str, production: dict[str, Any], expected_revision: int
    ) -> int:
        expected = parse_revision_value(expected_revision, "production")
        payload = dict(production)
        next_revision = require_revision_field(payload, "production")
        assert_next_revision(expected, next_revision)
        self.commit(
            run_id,
            CommitSpec(
                production=payload,
                production_expected_revision=expected,
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
            return self._read_resolved_config(validated_run_id)

    def _read_resolved_config(self, run_id: str) -> dict[str, Any]:
        path = self._owned_run_file(run_id, "resolved-config.yaml")
        if not path.exists():
            raise RunNotFoundError(
                run_id,
                "resolved-config.yaml missing",
                runs_root=self._root,
            )
        try:
            payload = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise PersistenceError(
                f"failed to decode resolved-config.yaml as UTF-8: {exc}"
            ) from exc
        try:
            parsed = load_yaml(payload)
        except Exception as exc:
            raise PersistenceError(f"failed to load resolved-config.yaml: {exc}") from exc
        if not isinstance(parsed, dict):
            raise PersistenceError("resolved-config.yaml must contain a mapping")
        from top_down_planning.config import ConfigError, validate_persisted_resolved_config

        try:
            validate_persisted_resolved_config(parsed)
        except ConfigError as exc:
            raise PersistenceError(
                f"resolved-config.yaml is invalid: {exc}"
            ) from exc
        return parsed

    def save_invocation(self, run_id: str, invocation: dict[str, Any]) -> None:
        """Persist CLI invocation metadata under the per-run commit lock.

        Presentation-only metadata is not journaled or digested; callers that need
        snapshot consistency with canonical files should use ``CommitSpec.invocation``.
        """

        with self._with_recovered_run(run_id) as validated_run_id:
            invocation = validate_persisted_invocation(invocation)
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
            return validate_persisted_invocation(
                self._read_json_object(path, label="invocation.json")
            )

    def reviews_dir(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        return self._assert_run_contained(run_dir, run_dir / "reviews")

    def capabilities_dir(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        return self._assert_run_contained(run_dir, run_dir / "capabilities")

    def artifacts_dir(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        return self._assert_run_contained(run_dir, run_dir / "artifacts")

    def active_capability_token_path(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        capability_dir = run_dir / "capability"
        if capability_dir.is_symlink():
            raise PersistenceError("run path capability must not be a symlink")
        return self._assert_run_contained(run_dir, capability_dir / "current")

    def agent_requests_dir(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        return self._assert_run_contained(run_dir, run_dir / AGENT_REQUESTS_DIR)

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
        validated_run_id = self._require_existing_run(run_id)
        capability_id, record, raw_secret = new_capability_record(
            run_id=validated_run_id,
            role=role,
            phase=phase,
            allowed_ops=allowed_ops,
            session_id=session_id,
            session_kind=session_kind,
            loop_id=loop_id,
            session_instance_id=session_instance_id,
            generation=generation,
        )
        capabilities_dir = self.capabilities_dir(validated_run_id)
        capabilities_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(capabilities_dir / f"{capability_id}.json", record)
        return capability_id, record, raw_secret

    def load_capability(self, run_id: str, capability_id: str) -> dict[str, Any]:
        validated_run_id = self._require_existing_run(run_id)
        return self._read_capability_record(validated_run_id, capability_id)

    def _read_capability_record(self, run_id: str, capability_id: str) -> dict[str, Any]:
        path = self._capability_record_path(run_id, capability_id)
        if not path.exists():
            raise RunNotFoundError(
                run_id,
                f"capability {capability_id} missing",
                runs_root=self._root,
            )
        return self._read_json_object(path, label=f"capability {capability_id}")

    def list_capabilities(self, run_id: str) -> list[dict[str, Any]]:
        validated_run_id = self._require_existing_run(run_id)
        capabilities_dir = self.capabilities_dir(validated_run_id)
        if not capabilities_dir.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(capabilities_dir.glob("*.json")):
            record_path = self._capability_record_path(validated_run_id, path.stem)
            records.append(
                self._read_json_object(record_path, label=f"capability {path.stem}")
            )
        return records

    def revoke_capability(self, run_id: str, capability_id: str) -> None:
        with self._with_recovered_run(run_id) as validated_run_id:
            record = self._read_capability_record(validated_run_id, capability_id)
            record["revoked"] = True
            validated_id = validate_store_id(capability_id, label="capability_id")
            atomic_write_json(
                self._capability_record_path(validated_run_id, validated_id),
                record,
            )

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
        run_dir = self.run_dir(run_id)
        snapshot_dir = self.artifacts_dir(run_id) / validated_snapshot_id
        if snapshot_dir.is_symlink():
            raise PersistenceError("artifact snapshot path must not be a symlink")
        return self._assert_run_contained(
            run_dir,
            snapshot_dir / validated_filename,
        )

    def write_artifact_bytes(
        self,
        run_id: str,
        snapshot_id: str,
        filename: str,
        data: bytes,
    ) -> str:
        validated_run_id = self._require_existing_run(run_id)
        path = self.artifact_path(validated_run_id, snapshot_id, filename)
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

    def delete_artifact_snapshot(self, run_id: str, snapshot_id: str) -> None:
        validated_run_id = self._require_existing_run(run_id)
        validated_snapshot_id = validate_store_id(snapshot_id, label="snapshot_id")
        run_dir = self.run_dir(validated_run_id)
        snapshot_dir = self.artifacts_dir(validated_run_id) / validated_snapshot_id
        contained = self._assert_run_contained(run_dir, snapshot_dir)
        if contained.is_symlink():
            raise PersistenceError("artifact snapshot path must not be a symlink")
        if contained.is_dir():
            shutil.rmtree(contained)

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
            review_expected[validated_review_id] = parse_revision_value(
                expected_revision,
                "review",
            )
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
            path = self._review_record_path(validated_run_id, validated_review_id)
            if not path.exists():
                raise RunNotFoundError(
                    validated_run_id,
                    f"review {validated_review_id} missing",
                    runs_root=self._root,
                )
            return canonicalize_persisted_review(
                validated_review_id,
                self._read_json_object(path, label=f"review {validated_review_id}"),
            )

    def list_reviews(self, run_id: str) -> list[dict[str, Any]]:
        with self._with_recovered_run(run_id) as validated_run_id:
            return self._read_reviews(validated_run_id)

    def _read_reviews(self, run_id: str) -> list[dict[str, Any]]:
        reviews_dir = self.reviews_dir(run_id)
        if not reviews_dir.is_dir():
            return []
        reviews: list[dict[str, Any]] = []
        for path in sorted(reviews_dir.glob("*.json")):
            review_path = self._review_record_path(run_id, path.stem)
            reviews.append(
                canonicalize_persisted_review(
                    path.stem,
                    self._read_json_object(review_path, label=f"review {path.stem}"),
                )
            )
        return reviews

    def _recover_incomplete_transactions(self, run_id: str) -> None:
        """Recover journaled transactions. Caller must hold the per-run commit lock."""
        run_dir = self.run_dir(run_id)
        if not run_dir.is_dir():
            return
        for stage_dir in sorted(run_dir.glob(".stage-*")):
            if stage_dir.is_symlink():
                raise PersistenceError("transaction stage directory must not be a symlink")
            if stage_dir.is_dir():
                shutil.rmtree(stage_dir, ignore_errors=True)
        for retired_dir in sorted(run_dir.glob(".retired-txn-*")):
            if retired_dir.is_symlink():
                raise PersistenceError("retired transaction directory must not be a symlink")
            if retired_dir.is_dir():
                shutil.rmtree(retired_dir, ignore_errors=True)
        txn_dir = validate_run_transactions_for_recovery(run_dir, run_id)
        if txn_dir is None:
            return
        self._recover_transaction_dir(run_id, run_dir, txn_dir)

    def _recover_transaction_dir(
        self,
        run_id: str,
        run_dir: Path,
        txn_dir: Path,
    ) -> None:
        txn_id = txn_dir.name.removeprefix(".txn-")
        if not txn_id:
            raise TransactionRecoveryError(
                "invalid transaction directory name",
                run_id=run_id,
                txn_id="unknown",
            )

        journal_path = self._txn_journal_path(txn_dir)
        if not journal_path.is_file():
            raise TransactionRecoveryError(
                "transaction journal missing",
                run_id=run_id,
                txn_id=txn_id,
            )

        journal = self._read_transaction_journal(journal_path, run_id, txn_id)
        parsed = parse_recovery_journal(journal, run_id=run_id, expected_txn_id=txn_id)
        status = parsed.status
        if status not in KNOWN_TXN_STATUSES:
            raise TransactionRecoveryError(
                f"unknown transaction status: {status}",
                run_id=run_id,
                txn_id=txn_id,
            )
        staged_files = [journal_file_entry_as_dict(entry) for entry in parsed.files]
        journal_events = parsed.events
        for entry in staged_files:
            name = str(entry.get("name") or "")
            if name:
                self._txn_staged_path(txn_dir, name)
        self._txn_backups_dir(txn_dir)
        replaced = parsed.replaced

        for name in parsed.backups:
            backup_path = self._txn_backup_path(txn_dir, name)
            if not backup_path.is_file():
                raise TransactionRecoveryError(
                    f"transaction journal backup missing on disk: {name}",
                    run_id=run_id,
                    txn_id=txn_id,
                )

        if status in {"prepared", "replacing"}:
            if status == "replacing" and replaced_destinations_match(run_dir, parsed):
                if txn_id and journal_events:
                    self._ensure_events_appended(
                        run_id,
                        txn_id,
                        parsed,
                    )
                self._retire_transaction_dir(run_dir, txn_dir)
                return
            self._rollback_replaced_files(
                run_dir,
                staged_files,
                self._collect_names_for_rollback(
                    run_dir,
                    staged_files,
                    replaced,
                ),
                txn_dir,
            )
            self._retire_transaction_dir(run_dir, txn_dir)
            return

        if status == "appending_events":
            require_committed_destinations(
                run_dir,
                parsed,
                run_id=run_id,
                txn_id=txn_id,
            )
            if txn_id and journal_events:
                self._ensure_events_appended(
                    run_id,
                    txn_id,
                    parsed,
                )
            self._retire_transaction_dir(run_dir, txn_dir)
            return

        if status == "committed":
            require_committed_destinations(
                run_dir,
                parsed,
                run_id=run_id,
                txn_id=txn_id,
            )
            if txn_id and journal_events:
                self._ensure_events_appended(
                    run_id,
                    txn_id,
                    parsed,
                )
            self._retire_transaction_dir(run_dir, txn_dir)
            return

    def _validate_run_created_anchor(
        self,
        run_id: str,
        events: list[dict[str, Any]],
    ) -> None:
        validate_run_created_anchor(run_id, events)

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
        validate_event_log_integrity(events)

    def _parse_events_text(self, text: str, events_path: Path) -> list[dict[str, Any]]:
        return parse_canonical_events_text(text, events_path=events_path)

    def _ensure_events_file_append_boundary(self, run_id: str) -> None:
        events_path = self._events_path(run_id)
        if not events_path.is_file():
            return
        data = events_path.read_bytes()
        if not data or data.endswith(b"\n"):
            return
        trailing = data.rsplit(b"\n", 1)[-1]
        if not trailing.strip():
            self._atomically_publish_events_bytes(events_path, data + b"\n")
            return
        try:
            payload = json.loads(trailing)
        except json.JSONDecodeError as exc:
            raise PersistenceError(
                f"events.jsonl has malformed trailing content in {events_path}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise PersistenceError(
                f"events.jsonl trailing content in {events_path} must be a JSON object"
            )
        self._require_journaled_event_fields(payload)
        self._atomically_publish_events_bytes(events_path, data + b"\n")

    def _verify_events_journal_boundary(
        self,
        run_id: str,
        txn_id: str,
        *,
        events_base_size: int,
        events_base_digest: str,
    ) -> None:
        events_path = self._events_path(run_id)
        if events_base_size == 0 and events_base_digest == digest_bytes(b""):
            if events_path.is_file() and events_path.stat().st_size > 0:
                raise TransactionRecoveryError(
                    "events append boundary mismatch",
                    run_id=run_id,
                    txn_id=txn_id,
                )
            return
        if not events_path.is_file():
            raise TransactionRecoveryError(
                "events append boundary mismatch",
                run_id=run_id,
                txn_id=txn_id,
            )
        data = events_path.read_bytes()
        if len(data) < events_base_size:
            raise TransactionRecoveryError(
                "events append boundary mismatch",
                run_id=run_id,
                txn_id=txn_id,
            )
        prefix = data[:events_base_size]
        if digest_bytes(prefix) != events_base_digest:
            raise TransactionRecoveryError(
                "events append boundary mismatch",
                run_id=run_id,
                txn_id=txn_id,
            )

    def _load_event_payloads(
        self,
        run_id: str,
        *,
        validate_integrity: bool = True,
    ) -> list[dict[str, Any]]:
        events_path = self._events_path(run_id)
        if not events_path.is_file():
            return []
        text = events_path.read_text(encoding="utf-8")
        events = self._parse_events_text(text, events_path)
        if validate_integrity:
            self._validate_event_log_integrity(events)
        return events

    def _destination_for_staged_entry(self, run_dir: Path, entry: dict[str, Any]) -> Path:
        if entry.get("kind") == "review":
            review_id = str(entry.get("review_id") or "")
            return self._assert_run_contained(
                run_dir,
                run_dir / "reviews" / f"{review_id}.json",
            )
        if entry.get("kind") == "artifact":
            snapshot_id = str(entry.get("snapshot_id") or "")
            filename = str(entry.get("filename") or "")
            return self._assert_run_contained(
                run_dir,
                run_dir / "artifacts" / snapshot_id / filename,
            )
        return self._assert_run_contained(run_dir, run_dir / str(entry.get("name") or ""))

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
        txn_dir: Path,
    ) -> None:
        entry_by_name = {str(entry.get("name") or ""): entry for entry in staged_files}
        for name in replaced:
            entry = entry_by_name.get(name)
            if entry is None:
                continue
            dest = self._destination_for_staged_entry(run_dir, entry)
            backup_path = self._txn_backup_path(txn_dir, name)
            if entry.get("kind") == "artifact":
                snapshot_dir = dest.parent
                if snapshot_dir.is_dir():
                    quarantine = lexical_txn_owned_path(
                        txn_dir,
                        txn_dir / f"rolled-back-artifact-{entry.get('snapshot_id')}",
                    )
                    try:
                        if dest.exists():
                            dest.unlink()
                        if snapshot_dir.is_dir() and not any(snapshot_dir.iterdir()):
                            snapshot_dir.rmdir()
                    except OSError:
                        if snapshot_dir.exists():
                            snapshot_dir.rename(quarantine)
                continue
            if backup_path.is_file():
                shutil.copy2(backup_path, dest)
            elif dest.exists():
                dest.unlink()

    def _journal_events_suffix_bytes(self, events: list[dict[str, Any]]) -> bytes:
        return journal_events_suffix_bytes(events)

    def _ensure_events_appended(
        self,
        run_id: str,
        txn_id: str,
        parsed: ParsedRecoveryJournal,
    ) -> None:
        if not parsed.events:
            return

        verify_events_append_recoverable(
            self.run_dir(run_id),
            parsed,
            run_id=run_id,
            txn_id=txn_id,
        )
        events_path = self._events_path(run_id)
        current = events_path.read_bytes() if events_path.is_file() else b""
        expected_suffix = journal_events_suffix_bytes(parsed.events)
        target = current[: parsed.events_base_size] + expected_suffix
        if current != target:
            self._atomically_publish_events_bytes(events_path, target)

    def _atomically_publish_events_bytes(self, events_path: Path, data: bytes) -> None:
        tmp_path = events_path.with_name(
            f".{events_path.name}.repair-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
        try:
            tmp_path.write_bytes(data)
            if tmp_path.read_bytes() != data:
                raise PersistenceError("temporary events repair write incomplete")
            tmp_path.replace(events_path)
        finally:
            tmp_path.unlink(missing_ok=True)

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

    def _require_existing_run(self, run_id: str) -> str:
        validated_run_id = validate_run_id(run_id)
        run_dir = self.run_dir(validated_run_id)
        if not run_dir.is_dir():
            raise RunNotFoundError(
                validated_run_id,
                "run directory missing",
                runs_root=self._root,
            )
        if not (run_dir / "run.json").is_file():
            raise RunNotFoundError(
                validated_run_id,
                "run.json missing",
                runs_root=self._root,
            )
        self._verify_canonical_run_identity(validated_run_id, run_dir)
        return validated_run_id

    def _verify_canonical_run_identity(self, run_id: str, run_dir: Path) -> None:
        payload = self._read_json_object(run_dir / "run.json", label="run.json")
        persisted_id = str(payload.get("id") or "").strip()
        if persisted_id != run_id:
            raise PersistenceError("run.id does not match run directory id")

    def _retire_transaction_dir(self, run_dir: Path, txn_dir: Path) -> None:
        txn_id = txn_dir.name.removeprefix(".txn-")
        retired_dir = self._assert_run_contained(
            run_dir,
            run_dir / f".retired-txn-{txn_id}-{uuid.uuid4().hex[:8]}",
        )
        txn_dir.rename(retired_dir)
        try:
            shutil.rmtree(retired_dir)
        except OSError:
            return

    def _run_path(self, run_id: str) -> Path:
        path = self._owned_run_file(run_id, "run.json")
        self._require_file(path, run_id)
        return path

    def _read_run(self, run_id: str) -> dict[str, Any]:
        payload = self._read_json_object(self._run_path(run_id), label="run.json")
        payload = validate_canonical_run(run_id, payload)
        binding = payload.get("context_snapshot_binding")
        if binding is not None:
            validate_context_snapshot_binding(binding)
        return payload

    def _plan_path(self, run_id: str) -> Path:
        path = self._owned_run_file(run_id, "plan.json")
        self._require_file(path, run_id)
        return path

    def _read_plan(self, run_id: str) -> dict[str, Any]:
        payload = self._read_json_object(self._plan_path(run_id), label="plan.json")
        return canonicalize_persisted_plan(payload)

    def _production_path(self, run_id: str) -> Path:
        path = self._owned_run_file(run_id, "production.json")
        self._require_file(path, run_id)
        return path

    def _read_production(self, run_id: str) -> dict[str, Any]:
        payload = self._read_json_object(
            self._production_path(run_id),
            label="production.json",
        )
        return validate_persisted_production(payload, plan=self._read_plan(run_id))

    def _read_review_revision(self, run_id: str, review_id: str) -> int:
        path = self._review_record_path(run_id, review_id)
        if not path.exists():
            return 0
        payload = self._read_json_object(path, label=f"review {review_id}")
        if "revision" not in payload:
            return 0
        return parse_revision_value(payload["revision"], "review")

    def _events_path(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        return self._assert_run_contained(run_dir, run_dir / "events.jsonl")

    def _require_file(self, path: Path, run_id: str) -> None:
        if not path.exists():
            raise RunNotFoundError(
                run_id,
                f"missing {path.name}",
                runs_root=self._root,
            )

    def _read_json_object(self, path: Path, *, label: str | None = None) -> dict[str, Any]:
        file_label = label or path.name
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except FileNotFoundError as exc:
            raise RunNotFoundError(
                path.parent.name,
                f"missing {path.name}",
                runs_root=self._root,
            ) from exc
        except UnicodeDecodeError as exc:
            raise PersistenceError(f"failed to decode {path} as UTF-8: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise PersistenceError(f"failed to load {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise PersistenceError(f"{file_label} must contain a JSON object")
        return payload
