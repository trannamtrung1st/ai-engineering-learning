"""Deterministic render manifest construction from confirmed plan state."""

from __future__ import annotations

import json
import re

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


def slugify_title(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:60] or "item"


def detect_output_mode(artifacts: OutputGoalArtifacts) -> tuple[OutputMode, str]:
    declared = artifacts.paths
    if len(declared) == 1 and not declared[0].endswith("/"):
        return OutputMode.SINGLE_DOCUMENT, declared[0]
    if not artifacts.deliverable_root:
        raise PlanningToolError(
            "Multi-file output goals must declare a deliverable root via a directory "
            "path or shared parent such as INDEX.md."
        )
    return OutputMode.MULTI_FILE, artifacts.deliverable_root


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


def _artifact_key(plan_item_id: str) -> str:
    suffix = plan_item_id.removeprefix("item-")
    return f"todo-item-{suffix}"


def _relative_path_for_item(
    *,
    order: int,
    slug: str,
    output_mode: OutputMode,
) -> str | None:
    if output_mode == OutputMode.SINGLE_DOCUMENT:
        return None
    return f"items/{order:03d}-{slug}.yaml"


def _publish_relative_path_for_item(
    *,
    set_order: int,
    slug: str,
    output_mode: OutputMode,
) -> str | None:
    if output_mode == OutputMode.SINGLE_DOCUMENT:
        return None
    return f"{set_order:02d}-{slug}.yaml"


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
    output_mode, final_path = detect_output_mode(goal_artifacts)
    render_config_digest = compute_render_config_digest(render_config)
    used_slugs: set[str] = set()
    manifest_items: list[RenderManifestItem] = []

    for set_order, item in enumerate(leaves, start=1):
        slug = _resolve_slug(item.title, used_slugs)
        manifest_items.append(
            RenderManifestItem(
                plan_item_id=item.id,
                top_level_branch_id=_top_level_branch_id(plan, item),
                order=item.order,
                set_order=set_order,
                title=item.title,
                dependencies=list(item.dependencies),
                assigned_batch_id="",  # filled by batcher
                artifact_key=_artifact_key(item.id),
                relative_path=_relative_path_for_item(
                    order=item.order,
                    slug=slug,
                    output_mode=output_mode,
                ),
                publish_relative_path=_publish_relative_path_for_item(
                    set_order=set_order,
                    slug=slug,
                    output_mode=output_mode,
                ),
                section_order=item.order if output_mode == OutputMode.SINGLE_DOCUMENT else None,
            )
        )

    batch_assignments = assign_render_batches(
        plan,
        manifest_items,
        render_config=render_config,
    )
    for entry, batch_id in zip(manifest_items, batch_assignments, strict=True):
        entry.assigned_batch_id = batch_id

    return RenderManifest(
        plan_digest=plan_digest,
        output_goal_digest=output_goal_digest,
        render_config_digest=render_config_digest,
        output_mode=output_mode,
        final_relative_path=final_path,
        deliverable_root=goal_artifacts.deliverable_root,
        declared_set_level_files=list(goal_artifacts.declared_set_level_files),
        items=manifest_items,
    )


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
