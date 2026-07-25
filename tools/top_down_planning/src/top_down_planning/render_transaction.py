"""Validate structured render batch transactions."""

from __future__ import annotations

from top_down_planning.models import (
    OutputMode,
    RenderBatchTransaction,
    RenderManifest,
    RenderManifestItem,
)
from top_down_planning.paths import validate_relative_path


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

        if artifact.artifact_key != manifest_item.artifact_key:
            errors.append(
                f"artifact_key mismatch for {artifact.plan_item_id}: "
                f"expected {manifest_item.artifact_key!r}, got {artifact.artifact_key!r}"
            )
        if artifact.artifact_key in seen_keys:
            errors.append(f"duplicate artifact_key {artifact.artifact_key!r}")
        seen_keys.add(artifact.artifact_key)

        if manifest.output_mode == OutputMode.MULTI_FILE:
            if artifact.relative_path != manifest_item.relative_path:
                errors.append(
                    f"relative_path mismatch for {artifact.plan_item_id}"
                )
            if artifact.relative_path:
                try:
                    normalized = validate_relative_path(
                        artifact.relative_path, label="relative_path"
                    )
                except ValueError as exc:
                    errors.append(str(exc))
                else:
                    if normalized in seen_paths:
                        errors.append(f"duplicate relative_path {normalized!r}")
                    seen_paths.add(normalized)
        else:
            if artifact.section_order != manifest_item.section_order:
                errors.append(
                    f"section_order mismatch for {artifact.plan_item_id}"
                )

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
