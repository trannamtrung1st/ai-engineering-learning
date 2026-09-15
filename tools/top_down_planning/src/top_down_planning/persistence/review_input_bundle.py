"""Immutable review-input bundles for reviewer session startup."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core_tools.persistence import PersistenceError, digest_bytes, exclusive_create_bytes
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.path_containment import lexical_run_owned_path
from top_down_planning.persistence.path_ids import validate_store_id

REVIEW_INPUT_BUNDLE_SCHEMA_VERSION = 1
REVIEW_INPUTS_DIRNAME = "review-inputs"
BOOTSTRAP_SIDECAR_NAME = "_bootstrap.json"

SECRET_KEYS = frozenset(
    {
        "capability_token",
        "token",
        "secret",
        "password",
        "credential",
        "raw_secret",
        "api_key",
        "access_token",
    }
)

TRUSTED_BOOTSTRAP_KEYS = frozenset(
    {
        "run_id",
        "phase",
        "type",
        "loop_id",
        "purpose",
        "scope",
        "target_revision",
        "target_digest",
        "stage",
        "lifecycle_status",
        "finding_set_id",
        "review_policy",
        "review_budgets",
        "respond_contract",
        "protocol_instructions",
        "tool_instructions",
        "review_record_schema_version",
        "review_contract_version",
        "family_protocol_enabled",
        "agent_context",
        "rubric_items",
        "required_audit_passes",
        "output_revision",
        "plan_revision",
        "review_limits",
    }
)

# Logical kind → (package key, filename)
MATERIAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("plan", "plan", "plan.json"),
    ("production", "production", "production.json"),
    ("plan_contracts", "plan_contracts", "plan_contracts.json"),
    ("evidence", "evidence_by_item", "evidence.json"),
    ("analysis_context", "analysis_context", "analysis_context.json"),
    ("sub_tdp_evidence", "sub_tdp_evidence", "sub_tdp_evidence.json"),
    ("integrated_deliverables", "integrated_deliverables", "integrated_deliverables.json"),
    ("active_families", "active_families", "active_families.json"),
    ("family_verification_view", "family_verification_view", "family_verification_view.json"),
)


@dataclass(frozen=True)
class ReviewInputBundle:
    """Durable snapshot of reviewer inputs for one logical review attempt."""

    run_id: str
    loop_id: str
    attempt_id: str
    review_type: str
    stage: str
    bundle_dir: Path
    manifest_path: Path
    manifest_relpath: str
    manifest: dict[str, Any]
    reused: bool
    bootstrap_fields: dict[str, Any] = field(default_factory=dict)


def review_attempt_id(loop: ReviewLoop | dict[str, Any]) -> str:
    """Return a stable attempt id for a reviewer loop stage and revision."""

    if isinstance(loop, ReviewLoop):
        stage = str(loop.active_stage or "initial_review")
        target_revision = int(loop.target_revision)
        revision_cycles = int(loop.revision_cycles)
        finding_set_id = str(loop.finding_set_id or "").strip()
    else:
        stage = str(loop.get("active_stage") or "initial_review").strip() or "initial_review"
        target_revision = int(loop.get("target_revision") or 0)
        revision_cycles = int(loop.get("revision_cycles") or 0)
        finding_set_id = str(loop.get("finding_set_id") or "").strip()
    base = f"{stage}-rev{target_revision}-cycle{revision_cycles}"
    if finding_set_id:
        validate_store_id(finding_set_id, label="finding_set_id")
        return validate_store_id(f"{base}-{finding_set_id}", label="review_attempt_id")
    return validate_store_id(base, label="review_attempt_id")


def review_inputs_dir(store: RunStore, run_id: str) -> Path:
    """Return the contained review-inputs directory for a run."""

    getter = getattr(store, "review_inputs_dir", None)
    if callable(getter):
        return Path(getter(run_id))
    run_dir = store.run_dir(run_id)
    path = run_dir / REVIEW_INPUTS_DIRNAME
    if path.is_symlink():
        raise PersistenceError("run path review-inputs must not be a symlink")
    return lexical_run_owned_path(run_dir, path)


def workspace_relative_path(workspace: Path, path: Path) -> str:
    """Return a workspace-relative POSIX path for provider prompts."""

    try:
        relative = path.resolve().relative_to(workspace.resolve())
    except ValueError:
        relative = Path(os.path.relpath(path.resolve(), workspace.resolve()))
    return relative.as_posix()


def extract_trusted_bootstrap_fields(review_package: dict[str, Any]) -> dict[str, Any]:
    """Return protocol/identity fields that remain inline in the bootstrap request."""

    trusted: dict[str, Any] = {}
    for key in TRUSTED_BOOTSTRAP_KEYS:
        if key in review_package:
            trusted[key] = _strip_secrets(review_package[key])
    return trusted


def split_review_material(review_package: dict[str, Any]) -> dict[str, Any]:
    """Return named review-material payloads keyed by logical kind."""

    material: dict[str, Any] = {}
    consumed = set(TRUSTED_BOOTSTRAP_KEYS)
    for kind, package_key, _filename in MATERIAL_FIELDS:
        if package_key in review_package:
            material[kind] = _strip_secrets(review_package[package_key])
            consumed.add(package_key)
    leftover: dict[str, Any] = {}
    for key, value in review_package.items():
        if key in consumed:
            continue
        if str(key).lower() in SECRET_KEYS:
            continue
        leftover[str(key)] = _strip_secrets(value)
    if leftover:
        material["review_context"] = leftover
    return material


def materialize_review_input_bundle(
    store: RunStore,
    run_id: str,
    *,
    loop: ReviewLoop,
    review_package: dict[str, Any],
    workspace: Path,
) -> ReviewInputBundle:
    """Write or reuse an immutable review-input bundle for this review attempt."""

    validated_run_id = validate_store_id(run_id, label="run_id")
    loop_id = validate_store_id(loop.id, label="loop_id")
    attempt_id = review_attempt_id(loop)
    stage = str(loop.active_stage or review_package.get("stage") or "initial_review")
    review_type = str(loop.type or review_package.get("type") or "")
    run_dir = store.run_dir(validated_run_id)
    inputs_root = review_inputs_dir(store, validated_run_id)
    if inputs_root.is_symlink():
        raise PersistenceError("run path review-inputs must not be a symlink")
    loop_dir = lexical_run_owned_path(run_dir, inputs_root / loop_id)
    dest = lexical_run_owned_path(run_dir, loop_dir / attempt_id)
    manifest_path = dest / "manifest.json"
    if manifest_path.is_file():
        return _load_bundle(
            run_id=validated_run_id,
            loop_id=loop_id,
            attempt_id=attempt_id,
            review_type=review_type,
            stage=stage,
            dest=dest,
            workspace=workspace,
            reused=True,
        )
    if dest.exists():
        raise PersistenceError(
            "review-input bundle directory exists without a published manifest"
        )

    material = split_review_material(review_package)
    trusted = extract_trusted_bootstrap_fields(review_package)
    staging = lexical_run_owned_path(
        run_dir,
        run_dir / f".stage-review-input-{uuid.uuid4().hex[:8]}",
    )
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        inputs: list[dict[str, Any]] = []
        filename_by_kind = {kind: filename for kind, _key, filename in MATERIAL_FIELDS}
        filename_by_kind["review_context"] = "review_context.json"
        for kind, payload in material.items():
            filename = filename_by_kind.get(kind, f"{kind}.json")
            data = _canonical_json_bytes(payload)
            file_path = staging / filename
            exclusive_create_bytes(file_path, data)
            inputs.append(
                {
                    "kind": kind,
                    "path": filename,
                    "required": True,
                    "sha256": digest_bytes(data),
                    "size_bytes": len(data),
                }
            )
        inputs.sort(key=lambda entry: str(entry["kind"]))
        manifest = {
            "schema_version": REVIEW_INPUT_BUNDLE_SCHEMA_VERSION,
            "review_type": review_type,
            "stage": stage,
            "loop_id": loop_id,
            "run_id": validated_run_id,
            "attempt_id": attempt_id,
            "target_revision": int(loop.target_revision),
            "inputs": inputs,
        }
        exclusive_create_bytes(
            staging / "manifest.json",
            _canonical_json_bytes(manifest),
        )
        exclusive_create_bytes(
            staging / BOOTSTRAP_SIDECAR_NAME,
            _canonical_json_bytes(trusted),
        )
        loop_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(staging, dest)
        except OSError:
            if manifest_path.is_file():
                shutil.rmtree(staging, ignore_errors=True)
                return _load_bundle(
                    run_id=validated_run_id,
                    loop_id=loop_id,
                    attempt_id=attempt_id,
                    review_type=review_type,
                    stage=stage,
                    dest=dest,
                    workspace=workspace,
                    reused=True,
                )
            raise
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return _load_bundle(
        run_id=validated_run_id,
        loop_id=loop_id,
        attempt_id=attempt_id,
        review_type=review_type,
        stage=stage,
        dest=dest,
        workspace=workspace,
        reused=False,
    )


def _load_bundle(
    *,
    run_id: str,
    loop_id: str,
    attempt_id: str,
    review_type: str,
    stage: str,
    dest: Path,
    workspace: Path,
    reused: bool,
) -> ReviewInputBundle:
    manifest_path = dest / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise PersistenceError("review-input manifest must be an object")
    _verify_bundle_inputs(dest, manifest)
    sidecar = dest / BOOTSTRAP_SIDECAR_NAME
    bootstrap_fields: dict[str, Any] = {}
    if sidecar.is_file():
        loaded = json.loads(sidecar.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            bootstrap_fields = loaded
    return ReviewInputBundle(
        run_id=run_id,
        loop_id=loop_id,
        attempt_id=attempt_id,
        review_type=str(manifest.get("review_type") or review_type),
        stage=str(manifest.get("stage") or stage),
        bundle_dir=dest,
        manifest_path=manifest_path,
        manifest_relpath=workspace_relative_path(workspace, manifest_path),
        manifest=manifest,
        reused=reused,
        bootstrap_fields=bootstrap_fields,
    )


def _verify_bundle_inputs(dest: Path, manifest: dict[str, Any]) -> None:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list):
        raise PersistenceError("review-input manifest is missing inputs")
    for entry in inputs:
        if not isinstance(entry, dict):
            raise PersistenceError("review-input manifest input is invalid")
        relative = str(entry.get("path") or "")
        if (
            not relative
            or "/" in relative
            or "\\" in relative
            or relative.startswith(".")
        ):
            raise PersistenceError("review-input path must be a plain filename")
        path = dest / relative
        if not path.is_file() or path.is_symlink():
            raise PersistenceError(f"review-input {relative!r} is missing")
        data = path.read_bytes()
        expected_size = int(entry.get("size_bytes") or -1)
        expected_hash = str(entry.get("sha256") or "")
        if expected_size != len(data):
            raise PersistenceError(
                f"review-input {relative!r} size does not match the manifest"
            )
        if expected_hash != digest_bytes(data):
            raise PersistenceError(
                f"review-input {relative!r} hash does not match the manifest"
            )


def _canonical_json_bytes(payload: Any) -> bytes:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                continue
            cleaned[str(key)] = _strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    return value
