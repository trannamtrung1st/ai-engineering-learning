"""Deterministic per-node render manifest construction."""

from __future__ import annotations

import json
from pathlib import Path

from top_down_planning.digest import compute_render_config_digest, digest_text
from top_down_planning.models import PlanState, RenderConfig, RenderManifest
from top_down_planning.render_batcher import assign_wave_ids
from top_down_planning.render_scheduler import build_progressive_schedule


def build_render_manifest(
    plan: PlanState,
    *,
    run_id: str,
    plan_digest: str,
    output_goal_digest: str,
    render_config: RenderConfig,
    render_dependencies: dict[str, list[str]] | None = None,
) -> tuple[RenderManifest, list[str]]:
    items, errors = build_progressive_schedule(
        plan,
        render_config=render_config,
        render_dependencies=render_dependencies,
    )
    if not errors and items:
        wave_ids = assign_wave_ids(plan, items, render_config=render_config)
        for item, wave_id in zip(items, wave_ids, strict=True):
            item.assigned_wave_id = wave_id

    return (
        RenderManifest(
            run_id=run_id,
            plan_digest=plan_digest,
            output_goal_digest=output_goal_digest,
            render_config_digest=compute_render_config_digest(render_config),
            items=items,
        ),
        errors,
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
