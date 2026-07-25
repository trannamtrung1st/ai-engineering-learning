"""Deterministic synthesis of set-level deliverable files."""

from __future__ import annotations

from pathlib import PurePosixPath

import yaml

from top_down_planning.models import OutputMode, RenderManifest


def synthesize_set_level_files(
    manifest: RenderManifest,
    *,
    leaf_contents: dict[str, str],
    plan_summary: str = "",
) -> dict[str, str]:
    """Build declared set-level files from manifest metadata and leaf YAML."""
    if manifest.output_mode != OutputMode.MULTI_FILE:
        return {}

    declared = set(manifest.declared_set_level_files)
    if not declared:
        return {}

    synthesized: dict[str, str] = {}
    ordered_items = sorted(manifest.items, key=lambda entry: entry.set_order)

    if "INDEX.md" in declared:
        synthesized["INDEX.md"] = _build_index_md(manifest, ordered_items)

    if "manifest.yaml" in declared:
        synthesized["manifest.yaml"] = _build_manifest_yaml(manifest, ordered_items)

    if "planning-summary.md" in declared:
        synthesized["planning-summary.md"] = _build_planning_summary(
            manifest,
            ordered_items,
            plan_summary=plan_summary,
        )

    if "index.yaml" in declared:
        synthesized["index.yaml"] = _build_index_yaml(manifest, ordered_items)

    return synthesized


def _publish_name(item) -> str:
    if item.publish_relative_path:
        return PurePosixPath(item.publish_relative_path).name
    return f"{item.set_order:02d}-item.yaml"


def _build_index_md(manifest: RenderManifest, ordered_items) -> str:
    root = manifest.deliverable_root or "."
    lines = [
        "# TODO set index",
        "",
        f"Deliverable root: `{root.rstrip('/')}`",
        "",
        "| Order | File | Title | Dependencies |",
        "| --- | --- | --- | --- |",
    ]
    for item in ordered_items:
        deps = ", ".join(item.dependencies) if item.dependencies else "—"
        lines.append(
            f"| {item.set_order:02d} | `{_publish_name(item)}` | {item.title} | {deps} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _build_manifest_yaml(manifest: RenderManifest, ordered_items) -> str:
    entries = []
    for item in ordered_items:
        entries.append(
            {
                "set_order": item.set_order,
                "plan_item_id": item.plan_item_id,
                "artifact_key": item.artifact_key,
                "publish_path": item.publish_relative_path,
                "staging_path": item.relative_path,
                "title": item.title,
                "dependencies": list(item.dependencies),
            }
        )
    payload = {
        "deliverable_root": manifest.deliverable_root,
        "items": entries,
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _build_index_yaml(manifest: RenderManifest, ordered_items) -> str:
    entries = []
    for item in ordered_items:
        entries.append(
            {
                "set_order": item.set_order,
                "plan_item_id": item.plan_item_id,
                "artifact_key": item.artifact_key,
                "publish_path": item.publish_relative_path,
                "staging_path": item.relative_path,
                "title": item.title,
                "dependencies": list(item.dependencies),
            }
        )
    return yaml.safe_dump({"items": entries}, sort_keys=False, allow_unicode=True)


def _build_planning_summary(
    manifest: RenderManifest,
    ordered_items,
    *,
    plan_summary: str,
) -> str:
    lines = [
        "# Planning summary",
        "",
    ]
    if plan_summary.strip():
        lines.extend([plan_summary.strip(), ""])
    lines.extend(
        [
            f"Actionable leaves: {len(ordered_items)}",
            "",
            "## Items",
            "",
        ]
    )
    for item in ordered_items:
        lines.append(f"{item.set_order:02d}. **{item.title}** (`{item.plan_item_id}`)")
    return "\n".join(lines).rstrip() + "\n"
