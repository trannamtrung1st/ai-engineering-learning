"""Validate rendered artifact content against manifest expectations."""

from __future__ import annotations

import yaml

from top_down_planning.models import OutputMode, RenderManifest, RenderManifestItem


def validate_artifact_content(
    artifact_content: str,
    manifest_item: RenderManifestItem,
    *,
    output_mode: OutputMode,
) -> list[str]:
    """Return validation errors for a single artifact's content."""
    if output_mode != OutputMode.MULTI_FILE:
        return []

    errors: list[str] = []
    try:
        parsed = yaml.safe_load(artifact_content)
    except yaml.YAMLError as exc:
        errors.append(
            f"invalid YAML content for {manifest_item.plan_item_id}: {exc}"
        )
        return errors

    if not isinstance(parsed, dict):
        errors.append(
            f"content for {manifest_item.plan_item_id} must be a YAML mapping"
        )
        return errors

    expected_order = f"{manifest_item.set_order:02d}"
    order_value = parsed.get("order")
    if order_value is None:
        errors.append(
            f"missing order field for {manifest_item.plan_item_id}; "
            f"expected {expected_order!r}"
        )
    else:
        normalized = str(order_value).strip()
        if normalized != expected_order:
            errors.append(
                f"order mismatch for {manifest_item.plan_item_id}: "
                f"expected {expected_order!r}, got {normalized!r}"
            )

    for field in ("id", "title"):
        value = parsed.get(field)
        if value is None or not str(value).strip():
            errors.append(
                f"missing or empty {field} for {manifest_item.plan_item_id}"
            )

    return errors


def validate_transaction_content(
    artifacts: list,
    assigned_items: list[RenderManifestItem],
    *,
    output_mode: OutputMode,
) -> list[str]:
    """Validate content for all artifacts in a batch transaction."""
    assigned_by_id = {item.plan_item_id: item for item in assigned_items}
    errors: list[str] = []
    for artifact in artifacts:
        manifest_item = assigned_by_id.get(artifact.plan_item_id)
        if manifest_item is None:
            continue
        errors.extend(
            validate_artifact_content(
                artifact.content,
                manifest_item,
                output_mode=output_mode,
            )
        )
    return errors
