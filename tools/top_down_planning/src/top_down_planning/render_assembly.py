"""Deterministic assembly of staged render batch transactions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from top_down_planning.digest import digest_text
from top_down_planning.models import RenderBatchTransaction, RenderManifest
from top_down_planning.persistence import render_assembled_dir, render_batch_transaction_path
from top_down_planning.render_batcher import unique_batch_ids
from top_down_planning.render_tool import load_render_transaction


@dataclass(frozen=True)
class AssembledOutput:
    files: dict[str, str]
    digest: str


def load_valid_batch_transactions(
    output_dir: Path,
    manifest: RenderManifest,
) -> dict[str, RenderBatchTransaction]:
    transactions: dict[str, RenderBatchTransaction] = {}
    for batch_id in unique_batch_ids(manifest.items):
        path = render_batch_transaction_path(output_dir, batch_id)
        transactions[batch_id] = load_render_transaction(path)
    return transactions


def assemble_render_output(
    manifest: RenderManifest,
    transactions: dict[str, RenderBatchTransaction],
) -> AssembledOutput:
    errors = validate_assembly(manifest, transactions)
    if errors:
        raise ValueError("; ".join(errors))

    files: dict[str, str] = {}
    for item in manifest.items:
        batch_txn = transactions[item.assigned_batch_id]
        artifact = next(
            art for art in batch_txn.artifacts if art.plan_item_id == item.plan_item_id
        )
        rel_path = item.relative_path
        if rel_path is None:
            raise ValueError(f"missing relative_path for {item.plan_item_id}")
        files[rel_path] = artifact.content

    files[".internal/index.yaml"] = _build_folder_index(manifest)
    digest = compute_assembled_digest(files)
    return AssembledOutput(files=files, digest=digest)


def write_assembled_output(output_dir: Path, assembled: AssembledOutput) -> Path:
    assembled_dir = render_assembled_dir(output_dir)
    assembled_dir.mkdir(parents=True, exist_ok=True)
    for relative, content in assembled.files.items():
        target = assembled_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip() + "\n", encoding="utf-8")
    manifest_path = assembled_dir / "assembly-manifest.json"
    manifest_path.write_text(
        json.dumps({"digest": assembled.digest, "files": sorted(assembled.files.keys())}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return assembled_dir


def validate_assembly(
    manifest: RenderManifest,
    transactions: dict[str, RenderBatchTransaction],
) -> list[str]:
    errors: list[str] = []
    rendered_ids: set[str] = set()
    artifact_keys: set[str] = set()
    paths: set[str] = set()

    manifest_ids = {item.plan_item_id for item in manifest.items}

    for batch_id, txn in transactions.items():
        for artifact in txn.artifacts:
            if artifact.plan_item_id not in manifest_ids:
                errors.append(f"unknown rendered item {artifact.plan_item_id!r}")
            if artifact.plan_item_id in rendered_ids:
                errors.append(f"duplicate render of {artifact.plan_item_id!r}")
            rendered_ids.add(artifact.plan_item_id)

            if artifact.artifact_key in artifact_keys:
                errors.append(f"duplicate artifact key {artifact.artifact_key!r}")
            artifact_keys.add(artifact.artifact_key)

            if artifact.relative_path:
                if artifact.relative_path in paths:
                    errors.append(f"duplicate path {artifact.relative_path!r}")
                paths.add(artifact.relative_path)

    missing = manifest_ids - rendered_ids
    if missing:
        errors.append(f"missing rendered artifacts: {sorted(missing)}")

    for item in manifest.items:
        if item.plan_item_id not in rendered_ids:
            continue
        for dep in item.dependencies:
            if dep not in manifest_ids and dep not in rendered_ids:
                errors.append(f"unresolved dependency {dep!r} for {item.plan_item_id}")

    return errors


def compute_assembled_digest(files: dict[str, str]) -> str:
    payload = {key: files[key] for key in sorted(files.keys())}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return digest_text(canonical)


def _build_folder_index(manifest: RenderManifest) -> str:
    entries = []
    for item in sorted(manifest.items, key=lambda entry: entry.set_order):
        entries.append(
            {
                "plan_item_id": item.plan_item_id,
                "artifact_key": item.artifact_key,
                "artifact_role": item.artifact_role,
                "staging_path": item.relative_path,
                "publish_path": item.publish_relative_path,
                "set_order": item.set_order,
                "title": item.title,
                "dependencies": list(item.dependencies),
            }
        )
    return yaml.safe_dump({"items": entries}, sort_keys=False, allow_unicode=True)
