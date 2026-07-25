"""Deterministic render manifest construction from confirmed plan state."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from top_down_planning.digest import compute_render_config_digest, digest_text
from top_down_planning.errors import PlanningToolError
from top_down_planning.models import (
    OutputMode,
    PlanItem,
    PlanState,
    RenderConfig,
    RenderManifest,
    RenderManifestItem,
)
from top_down_planning.output_goal_artifacts import (
    OutputGoalArtifacts,
    parse_output_goal_artifacts,
)
from top_down_planning.render_brief import actionable_leaf_items
from top_down_planning.render_batcher import assign_render_batches

FINAL_BATCH_ID = "render-batch-final"
FINAL_ORDER_BASE = 9000
INTERMEDIATE_PREFIX = "intermediates"


def slugify_title(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:60] or "item"


def detect_output_mode(artifacts: OutputGoalArtifacts) -> OutputMode:
    declared = artifacts.paths
    if len(declared) == 1 and not declared[0].endswith("/"):
        return OutputMode.SINGLE_DOCUMENT
    if not artifacts.deliverable_root:
        raise PlanningToolError(
            "Multi-file output goals must declare a deliverable root via a directory "
            "path or shared parent such as INDEX.md."
        )
    return OutputMode.MULTI_FILE


def _top_level_branch_id(plan: PlanState, item: PlanItem) -> str:
    current = item
    while current.parent_id is not None:
        parent = plan.item_by_id(current.parent_id)
        if parent is None:
            break
        current = parent
    return current.id


def _resolve_slug(title: str, used: set[str]) -> str:
    base = slugify_title(title)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _intermediate_artifact_key(plan_item_id: str) -> str:
    suffix = plan_item_id.removeprefix("item-")
    return f"artifact-{suffix}"


def _intermediate_relative_path(batch_id: str, plan_item_id: str) -> str:
    return f"{INTERMEDIATE_PREFIX}/{batch_id}/{plan_item_id}.md"


def _build_final_manifest_items(
    final_paths: list[str],
    *,
    intermediate_count: int,
) -> list[RenderManifestItem]:
    items: list[RenderManifestItem] = []
    used_slugs: set[str] = set()
    order = FINAL_ORDER_BASE

    for index, path in enumerate(final_paths):
        order += 1
        basename = PurePosixPath(path).name
        slug = _resolve_slug(basename, used_slugs)
        items.append(
            RenderManifestItem(
                plan_item_id=f"final-{slug}",
                top_level_branch_id="final",
                order=order,
                set_order=intermediate_count + index + 1,
                title=f"Final deliverable: {path}",
                dependencies=[],
                assigned_batch_id=FINAL_BATCH_ID,
                artifact_key=f"final-{slug}",
                relative_path=path,
                publish_relative_path=path,
                artifact_role="final",
            )
        )

    return items


def build_render_manifest(
    plan: PlanState,
    *,
    plan_digest: str,
    output_goal_digest: str,
    output_goal_text: str,
    render_config: RenderConfig,
) -> RenderManifest:
    leaves = actionable_leaf_items(plan)
    goal_artifacts = parse_output_goal_artifacts(output_goal_text)
    if not goal_artifacts.final_paths:
        raise PlanningToolError(
            "Output goal must declare at least one file path under ## Output artifacts. "
            "Directory-only declarations are not sufficient for render."
        )
    output_mode = detect_output_mode(goal_artifacts)
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

    manifest_items.extend(
        _build_final_manifest_items(
            goal_artifacts.final_paths,
            intermediate_count=len(manifest_items),
        )
    )

    return RenderManifest(
        plan_digest=plan_digest,
        output_goal_digest=output_goal_digest,
        render_config_digest=render_config_digest,
        output_mode=output_mode,
        deliverable_root=goal_artifacts.deliverable_root,
        items=manifest_items,
    )


def manifest_matches_output_goal(manifest: RenderManifest, output_goal_text: str) -> bool:
    """Return False when a persisted manifest omits required final artifacts."""
    goal_artifacts = parse_output_goal_artifacts(output_goal_text)
    expected_final = set(goal_artifacts.final_paths)
    final_items = [item for item in manifest.items if item.artifact_role == "final"]
    actual_final = {item.relative_path for item in final_items if item.relative_path}
    if expected_final != actual_final:
        return False
    if expected_final and not all(
        item.assigned_batch_id == FINAL_BATCH_ID for item in final_items
    ):
        return False

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
        if item.artifact_role == "final":
            if not item.artifact_key.startswith("final-"):
                return False
            if item.assigned_batch_id != FINAL_BATCH_ID:
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
