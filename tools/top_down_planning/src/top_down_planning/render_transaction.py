"""Validate structured render batch transactions."""

from __future__ import annotations

from top_down_planning.models import (
    RenderBatchArtifact,
    RenderBatchTransaction,
    RenderManifest,
    RenderManifestItem,
)
from top_down_planning.paths import validate_relative_path
from top_down_planning.render_manifest import FINAL_BATCH_ID

_FORBIDDEN_PATH_PREFIXES = (".planning-output/", ".planning-output")


def validate_batch_transaction(
    transaction: RenderBatchTransaction,
    *,
    manifest: RenderManifest,
    assigned_items: list[RenderManifestItem],
    expected_batch_id: str,
    expected_plan_digest: str,
    expected_output_goal_digest: str,
    expected_render_config_digest: str,
) -> list[str]:
    errors = _validate_transaction_metadata(
        transaction,
        expected_batch_id=expected_batch_id,
        expected_plan_digest=expected_plan_digest,
        expected_output_goal_digest=expected_output_goal_digest,
        expected_render_config_digest=expected_render_config_digest,
    )
    if errors:
        return errors

    if expected_batch_id == FINAL_BATCH_ID:
        return validate_final_batch_transaction(transaction)

    return _validate_intermediate_batch_transaction(transaction, assigned_items=assigned_items)


def _validate_transaction_metadata(
    transaction: RenderBatchTransaction,
    *,
    expected_batch_id: str,
    expected_plan_digest: str,
    expected_output_goal_digest: str,
    expected_render_config_digest: str,
) -> list[str]:
    errors: list[str] = []

    if transaction.batch_id != expected_batch_id:
        errors.append(
            f"batch_id mismatch: expected {expected_batch_id!r}, got {transaction.batch_id!r}"
        )
    if transaction.plan_digest != expected_plan_digest:
        errors.append("plan_digest mismatch")
    if transaction.output_goal_digest != expected_output_goal_digest:
        errors.append("output_goal_digest mismatch")
    if transaction.render_config_digest != expected_render_config_digest:
        errors.append("render_config_digest mismatch")
    return errors


def validate_final_batch_transaction(transaction: RenderBatchTransaction) -> list[str]:
    errors: list[str] = []
    seen_items: set[str] = set()
    seen_keys: set[str] = set()
    seen_paths: set[str] = set()

    for artifact in transaction.artifacts:
        errors.extend(_validate_final_artifact(artifact, seen_items, seen_keys, seen_paths))

    return errors


def _validate_final_artifact(
    artifact: RenderBatchArtifact,
    seen_items: set[str],
    seen_keys: set[str],
    seen_paths: set[str],
) -> list[str]:
    errors: list[str] = []

    if artifact.plan_item_id in seen_items:
        errors.append(f"plan item {artifact.plan_item_id!r} rendered more than once")
    seen_items.add(artifact.plan_item_id)

    if artifact.artifact_key in seen_keys:
        errors.append(f"duplicate artifact_key {artifact.artifact_key!r}")
    seen_keys.add(artifact.artifact_key)

    if not artifact.relative_path:
        errors.append(f"missing relative_path for {artifact.plan_item_id!r}")
    else:
        errors.extend(_validate_safe_path(artifact.relative_path, label="relative_path"))
        normalized = _normalize_path(artifact.relative_path)
        if normalized is not None:
            if normalized in seen_paths:
                errors.append(f"duplicate relative_path {normalized!r}")
            seen_paths.add(normalized)

    if "publish_relative_path" in artifact.model_fields_set and artifact.publish_relative_path:
        errors.extend(
            _validate_safe_path(
                artifact.publish_relative_path,
                label="publish_relative_path",
            )
        )

    if not artifact.content.strip():
        errors.append(f"empty content for {artifact.plan_item_id!r}")

    return errors


def _validate_intermediate_batch_transaction(
    transaction: RenderBatchTransaction,
    *,
    assigned_items: list[RenderManifestItem],
) -> list[str]:
    errors: list[str] = []

    if not transaction.artifacts:
        errors.append("intermediate batch must record at least one artifact")

    assigned_by_id = {item.plan_item_id: item for item in assigned_items}
    assigned_keys = {item.artifact_key for item in assigned_items}
    seen_items: set[str] = set()
    seen_keys: set[str] = set()
    seen_paths: set[str] = set()

    for artifact in transaction.artifacts:
        if artifact.plan_item_id not in assigned_by_id:
            errors.append(
                f"artifact refers to unassigned plan item {artifact.plan_item_id!r}"
            )
            continue

        manifest_item = assigned_by_id[artifact.plan_item_id]
        if artifact.plan_item_id in seen_items:
            errors.append(
                f"plan item {artifact.plan_item_id!r} rendered more than once"
            )
        seen_items.add(artifact.plan_item_id)

        if manifest_item.relative_path is None:
            errors.append(
                f"missing relative_path in manifest for {artifact.plan_item_id}"
            )
        elif artifact.relative_path != manifest_item.relative_path:
            errors.append(
                f"relative_path mismatch for {artifact.plan_item_id}"
            )

        if artifact.artifact_key != manifest_item.artifact_key:
            errors.append(
                f"artifact_key mismatch for {artifact.plan_item_id}: "
                f"expected {manifest_item.artifact_key!r}, got {artifact.artifact_key!r}"
            )
        if artifact.artifact_key in seen_keys:
            errors.append(f"duplicate artifact_key {artifact.artifact_key!r}")
        seen_keys.add(artifact.artifact_key)

        if artifact.relative_path:
            normalized = _normalize_path(artifact.relative_path)
            if normalized is not None:
                if normalized in seen_paths:
                    errors.append(f"duplicate relative_path {normalized!r}")
                seen_paths.add(normalized)

        if not artifact.content.strip():
            errors.append(f"empty content for {artifact.plan_item_id}")

    for item in assigned_items:
        if item.plan_item_id not in seen_items:
            errors.append(f"assigned plan item {item.plan_item_id!r} omitted")

    if assigned_keys != seen_keys:
        missing = assigned_keys - seen_keys
        extra = seen_keys - assigned_keys
        if missing:
            errors.append(f"missing artifact keys: {sorted(missing)}")
        if extra:
            errors.append(f"unexpected artifact keys: {sorted(extra)}")

    return errors


def _normalize_path(path: str) -> str | None:
    try:
        return validate_relative_path(path, label="relative_path")
    except ValueError:
        return None


def _validate_safe_path(path: str, *, label: str) -> list[str]:
    errors: list[str] = []
    try:
        normalized = validate_relative_path(path, label=label)
    except ValueError as exc:
        return [str(exc)]

    lowered = normalized.lower()
    for prefix in _FORBIDDEN_PATH_PREFIXES:
        if lowered == prefix.rstrip("/") or lowered.startswith(prefix):
            errors.append(f"{label} must not write into .planning-output: {path!r}")
            break
    return errors
