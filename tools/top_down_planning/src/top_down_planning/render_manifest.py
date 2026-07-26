"""Deterministic render manifest construction from confirmed plan state."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from top_down_planning.digest import compute_render_config_digest, digest_text
from top_down_planning.models import (
    OutputMode,
    PlanItem,
    PlanState,
    RenderBatchStateEntry,
    RenderBatchStatus,
    RenderBatchTransaction,
    RenderConfig,
    RenderManifest,
    RenderManifestItem,
    RenderState,
)
from top_down_planning.render_brief import actionable_leaf_items
from top_down_planning.render_batcher import assign_render_batches, unique_batch_ids

FINAL_BATCH_ID = "render-batch-final"
FINAL_ORDER_BASE = 9000
INTERMEDIATE_PREFIX = "intermediates"


def slugify_title(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:60] or "item"


def _top_level_branch_id(plan: PlanState, item: PlanItem) -> str:
    current = item
    while current.parent_id is not None:
        parent = plan.item_by_id(current.parent_id)
        if parent is None:
            break
        current = parent
    return current.id


def _intermediate_artifact_key(plan_item_id: str) -> str:
    suffix = plan_item_id.removeprefix("item-")
    return f"artifact-{suffix}"


def _intermediate_relative_path(batch_id: str, plan_item_id: str) -> str:
    return f"{INTERMEDIATE_PREFIX}/{batch_id}/{plan_item_id}.md"


def scheduled_batch_ids(manifest: RenderManifest) -> list[str]:
    """Return intermediate batch ids plus the always-scheduled final batch."""
    batch_ids = unique_batch_ids(manifest.items)
    if FINAL_BATCH_ID not in batch_ids:
        batch_ids.append(FINAL_BATCH_ID)
    return batch_ids


def build_render_manifest(
    plan: PlanState,
    *,
    plan_digest: str,
    output_goal_digest: str,
    render_config: RenderConfig,
) -> RenderManifest:
    leaves = actionable_leaf_items(plan)
    render_config_digest = compute_render_config_digest(render_config)
    manifest_items: list[RenderManifestItem] = []

    for set_order, item in enumerate(leaves, start=1):
        manifest_items.append(
            RenderManifestItem(
                plan_item_id=item.id,
                top_level_branch_id=_top_level_branch_id(plan, item),
                order=item.order,
                set_order=set_order,
                title=item.title,
                dependencies=list(item.dependencies),
                assigned_batch_id="",  # filled by batcher
                artifact_key=_intermediate_artifact_key(item.id),
                artifact_role="intermediate",
            )
        )

    if manifest_items:
        batch_assignments = assign_render_batches(
            plan,
            manifest_items,
            render_config=render_config,
        )
        for entry, batch_id in zip(manifest_items, batch_assignments, strict=True):
            entry.assigned_batch_id = batch_id
            entry.relative_path = _intermediate_relative_path(batch_id, entry.plan_item_id)

    return RenderManifest(
        plan_digest=plan_digest,
        output_goal_digest=output_goal_digest,
        render_config_digest=render_config_digest,
        output_mode=OutputMode.SINGLE_DOCUMENT,
        deliverable_root=None,
        items=manifest_items,
    )


def _resolve_publish_path(artifact) -> str | None:
    if "publish_relative_path" in artifact.model_fields_set:
        return artifact.publish_relative_path
    return artifact.relative_path


def _infer_output_metadata(final_paths: list[str]) -> tuple[OutputMode, str | None]:
    if not final_paths:
        return OutputMode.SINGLE_DOCUMENT, None
    if len(final_paths) == 1:
        return OutputMode.SINGLE_DOCUMENT, None

    parents: set[str] = set()
    for path in final_paths:
        parent = str(PurePosixPath(path).parent)
        if parent and parent != ".":
            parents.add(parent.rstrip("/") + "/")

    deliverable_root: str | None
    if len(parents) == 1:
        deliverable_root = next(iter(parents))
    else:
        deliverable_root = None
    return OutputMode.MULTI_FILE, deliverable_root


def apply_final_transaction_to_manifest(
    manifest: RenderManifest,
    transaction: RenderBatchTransaction,
) -> RenderManifest:
    """Append agent-declared final items from the final batch transaction."""
    intermediate_items = [
        item for item in manifest.items if item.artifact_role == "intermediate"
    ]
    intermediate_count = len(intermediate_items)
    final_items: list[RenderManifestItem] = []
    publish_paths: list[str] = []

    for index, artifact in enumerate(transaction.artifacts, start=1):
        staging_path = artifact.relative_path
        if not staging_path:
            continue
        publish_path = _resolve_publish_path(artifact)
        if publish_path is not None:
            publish_paths.append(publish_path)

        final_items.append(
            RenderManifestItem(
                plan_item_id=artifact.plan_item_id,
                top_level_branch_id="final",
                order=FINAL_ORDER_BASE + index,
                set_order=intermediate_count + index,
                title=f"Final deliverable: {staging_path}",
                dependencies=[],
                assigned_batch_id=FINAL_BATCH_ID,
                artifact_key=artifact.artifact_key,
                relative_path=staging_path,
                publish_relative_path=publish_path,
                artifact_role="final",
            )
        )

    output_mode, deliverable_root = _infer_output_metadata(publish_paths)
    return manifest.model_copy(
        update={
            "items": intermediate_items + final_items,
            "output_mode": output_mode,
            "deliverable_root": deliverable_root,
        }
    )


def manifest_finals_are_committed(
    manifest: RenderManifest,
    render_state: RenderState | None,
) -> bool:
    """Return False when finals exist without a validated final batch transaction."""
    final_items = [item for item in manifest.items if item.artifact_role == "final"]
    if not final_items:
        return True
    if render_state is None:
        return False
    entry: RenderBatchStateEntry | None = render_state.batches.get(FINAL_BATCH_ID)
    return entry is not None and entry.status == RenderBatchStatus.VALID


def manifest_is_valid(manifest: RenderManifest) -> bool:
    """Return False when a persisted manifest has invalid render structure."""
    for item in manifest.items:
        if item.artifact_role not in {"intermediate", "final"}:
            return False
        if item.artifact_role == "intermediate":
            if not item.relative_path or not item.relative_path.startswith(
                f"{INTERMEDIATE_PREFIX}/"
            ):
                return False
            if not item.artifact_key.startswith("artifact-"):
                return False
            if not item.assigned_batch_id or item.assigned_batch_id == FINAL_BATCH_ID:
                return False
        if item.artifact_role == "final":
            if not item.artifact_key:
                return False
            if item.assigned_batch_id != FINAL_BATCH_ID:
                return False
            if not item.relative_path:
                return False
    return True


def compute_manifest_digest(manifest: RenderManifest) -> str:
    payload = manifest.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return digest_text(canonical)


def save_render_manifest(path: Path, manifest: RenderManifest) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_render_manifest(path: Path) -> RenderManifest:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return RenderManifest.model_validate(data)
