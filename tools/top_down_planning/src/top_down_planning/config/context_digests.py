"""Context spec vs snapshot digests and production-authorized snapshot rebase."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from top_down_planning.config.context import (
    build_context_snapshot_payload,
    compute_context_snapshot_digest_from_payload,
    compute_context_spec_digest_from_config,
    validate_guidance_for_binding,
)


class UnauthorizedContextMutationError(ValueError):
    """Production completion cannot rebase context snapshot for unexplained drift."""

    def __init__(
        self,
        message: str,
        *,
        unauthorized_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.unauthorized_paths = unauthorized_paths


def _guidance_digest_key(entry: dict[str, Any]) -> str | None:
    path = entry.get("path")
    if path:
        return str(path)
    text = str(entry.get("text") or "")
    if text:
        return f"guidance:inline:{text}"
    return None


def _format_snapshot_drift_label(key: str) -> str:
    if key.startswith("guidance:inline:"):
        text = key.removeprefix("guidance:inline:")
        preview = text if len(text) <= 40 else f"{text[:37]}..."
        return f"inline guidance ({preview!r})"
    return short_path_for_observability(key)


def authorized_production_workspace_paths(
    production: dict[str, Any],
    *,
    workspace: Path,
) -> set[str]:
    """Workspace paths attributable to persisted production output evidence."""

    authorized: set[str] = set()
    workspace_resolved = workspace.resolve()

    def add_ref(ref: object) -> None:
        ref_text = str(ref or "").strip()
        if not ref_text:
            return
        candidate = (workspace_resolved / ref_text).resolve()
        authorized.add(str(candidate))

    for entry in production.get("output_evidence") or []:
        if isinstance(entry, dict):
            add_ref(entry.get("ref"))

    for batch in production.get("batches") or []:
        if not isinstance(batch, dict):
            continue
        if batch.get("evidence_status") == "invalidated_by_reconciliation":
            continue
        result = batch.get("result")
        if not isinstance(result, dict):
            continue
        for output in result.get("outputs") or []:
            if isinstance(output, dict):
                add_ref(output.get("ref"))

    return authorized


def diff_snapshot_binding_paths(
    old_binding: dict[str, Any],
    new_binding: dict[str, Any],
) -> list[str]:
    """Return sorted paths whose resource, skill, or guidance digest changed."""

    changed: set[str] = set()

    def digest_maps(
        binding: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        resources: dict[str, str] = {}
        for entry in binding.get("resource_digests") or []:
            if isinstance(entry, dict) and entry.get("path"):
                resources[str(entry["path"])] = str(entry.get("digest") or "")
        skills: dict[str, str] = {}
        for entry in binding.get("skill_digests") or []:
            if isinstance(entry, dict) and entry.get("path"):
                skills[str(entry["path"])] = str(entry.get("digest") or "")
        guidance: dict[str, str] = {}
        for entry in binding.get("guidance_digests") or []:
            if not isinstance(entry, dict):
                continue
            key = _guidance_digest_key(entry)
            if key:
                guidance[key] = str(entry.get("digest") or "")
        return resources, skills, guidance

    old_resources, old_skills, old_guidance = digest_maps(old_binding)
    new_resources, new_skills, new_guidance = digest_maps(new_binding)
    for path in sorted(set(old_resources) | set(new_resources)):
        if old_resources.get(path) != new_resources.get(path):
            changed.add(path)
    for path in sorted(set(old_skills) | set(new_skills)):
        if old_skills.get(path) != new_skills.get(path):
            changed.add(path)
    for path in sorted(set(old_guidance) | set(new_guidance)):
        if old_guidance.get(path) != new_guidance.get(path):
            changed.add(path)
    return sorted(changed)


def validate_production_snapshot_rebase(
    old_binding: dict[str, Any],
    new_binding: dict[str, Any],
    production: dict[str, Any],
    *,
    workspace: Path,
) -> list[str]:
    """Authorize snapshot drift from production evidence; return changed paths."""

    changed_paths = diff_snapshot_binding_paths(old_binding, new_binding)
    if not changed_paths:
        return []

    authorized = authorized_production_workspace_paths(production, workspace=workspace)
    unauthorized = [path for path in changed_paths if path not in authorized]
    if unauthorized:
        joined = ", ".join(_format_snapshot_drift_label(path) for path in unauthorized[:5])
        suffix = "" if len(unauthorized) <= 5 else f" (+{len(unauthorized) - 5} more)"
        raise UnauthorizedContextMutationError(
            "production completion cannot rebase context snapshot: "
            f"unauthorized workspace changes detected ({joined}{suffix})",
            unauthorized_paths=tuple(unauthorized),
        )
    return changed_paths


def short_path_for_observability(path: str) -> str:
    """Redact absolute paths for audit events."""

    parts = Path(path).parts
    if len(parts) <= 2:
        return path
    return str(Path(*parts[-2:]))


def build_initial_context_snapshot_binding(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> tuple[dict[str, Any], str, str]:
    """Return binding payload, context_spec digest, and context_snapshot digest."""

    validate_guidance_for_binding(config, workspace=workspace)
    binding = build_context_snapshot_payload(config, workspace=workspace)
    spec_digest = compute_context_spec_digest_from_config(config, workspace=workspace)
    snapshot_digest = compute_context_snapshot_digest_from_payload(binding)
    return binding, spec_digest, snapshot_digest


def recompute_context_snapshot_binding(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> tuple[dict[str, Any], str]:
    binding = build_context_snapshot_payload(
        config,
        workspace=workspace,
        allow_missing_guidance_files=True,
    )
    return binding, compute_context_snapshot_digest_from_payload(binding)


__all__ = [
    "UnauthorizedContextMutationError",
    "authorized_production_workspace_paths",
    "build_initial_context_snapshot_binding",
    "diff_snapshot_binding_paths",
    "recompute_context_snapshot_binding",
    "short_path_for_observability",
    "validate_production_snapshot_rebase",
]
