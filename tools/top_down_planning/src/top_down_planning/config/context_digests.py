"""Context spec vs snapshot digests and production-authorized snapshot rebase."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from top_down_planning.config.binding_validation import (
    InvalidSnapshotBindingError,
    LEGACY_SNAPSHOT_BINDING_MESSAGE,
)
from top_down_planning.config.context import (
    build_context_snapshot_payload_with_diagnostics,
    compute_context_snapshot_digest_from_payload,
    compute_context_spec_digest_from_config,
    validate_guidance_for_binding,
)
from top_down_planning.config.snapshot_diagnostics import (
    format_unauthorized_mutation_message,
)
from top_down_planning.config.snapshot_policy import (
    CanonicalPathError,
    canonicalize_evidence_ref,
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


class InvalidProductionEvidenceError(ValueError):
    """Production evidence refs cannot be canonicalized for authorization."""

    def __init__(self, invalid_refs: tuple[str, ...]) -> None:
        joined = ", ".join(invalid_refs)
        super().__init__(
            f"production contains invalid evidence refs (recreate or fix production): {joined}"
        )
        self.invalid_refs = invalid_refs


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
    return key


def _production_evidence_ref_strings(production: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for entry in production.get("output_evidence") or []:
        if isinstance(entry, dict):
            ref_text = str(entry.get("ref") or "").strip()
            if ref_text:
                refs.append(ref_text)
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
                ref_text = str(output.get("ref") or "").strip()
                if ref_text:
                    refs.append(ref_text)
    return refs


def invalid_production_evidence_refs(
    production: dict[str, Any],
    *,
    workspace: Path,
) -> tuple[str, ...]:
    """Return evidence refs that fail canonicalization (corrupted production)."""

    invalid: list[str] = []
    for ref_text in _production_evidence_ref_strings(production):
        try:
            canonicalize_evidence_ref(ref_text, workspace=workspace)
        except CanonicalPathError:
            invalid.append(ref_text)
    return tuple(invalid)


def authorized_production_workspace_paths(
    production: dict[str, Any],
    *,
    workspace: Path,
) -> set[str]:
    """Canonical relative paths attributable to persisted production evidence.

    Uses the same evidence-ref canonicalization as artifact capture so authorized
    paths compare equal to snapshot binding keys (proposal §§8,10–11).
    """

    authorized: set[str] = set()
    for ref_text in _production_evidence_ref_strings(production):
        try:
            authorized.add(canonicalize_evidence_ref(ref_text, workspace=workspace))
        except CanonicalPathError:
            # Invalid refs are surfaced by invalid_production_evidence_refs /
            # validate_production_snapshot_rebase before authorization checks.
            continue
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
        resources_raw = binding.get("resource_digests") or {}
        skills_raw = binding.get("skill_digests") or {}
        if isinstance(resources_raw, list) or isinstance(skills_raw, list):
            raise InvalidSnapshotBindingError(LEGACY_SNAPSHOT_BINDING_MESSAGE)
        resources = {
            str(path): str(digest or "")
            for path, digest in dict(resources_raw).items()
        }
        skills = {
            str(path): str(digest or "")
            for path, digest in dict(skills_raw).items()
        }
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

    invalid_refs = invalid_production_evidence_refs(production, workspace=workspace)
    if invalid_refs:
        raise InvalidProductionEvidenceError(invalid_refs)

    authorized = authorized_production_workspace_paths(production, workspace=workspace)
    unauthorized = [path for path in changed_paths if path not in authorized]
    if unauthorized:
        raise UnauthorizedContextMutationError(
            format_unauthorized_mutation_message(unauthorized),
            unauthorized_paths=tuple(unauthorized),
        )
    return changed_paths


def short_path_for_observability(path: str) -> str:
    """Return canonical relative path for audit events (already relative after §9)."""

    if path.startswith("guidance:inline:"):
        return _format_snapshot_drift_label(path)
    return path


def build_initial_context_snapshot_binding(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> tuple[dict[str, Any], str, str]:
    """Return binding payload, context_spec digest, and context_snapshot digest."""

    validate_guidance_for_binding(config, workspace=workspace)
    binding, _diagnostics = build_context_snapshot_payload_with_diagnostics(
        config,
        workspace=workspace,
    )
    spec_digest = compute_context_spec_digest_from_config(config, workspace=workspace)
    snapshot_digest = compute_context_snapshot_digest_from_payload(binding)
    return binding, spec_digest, snapshot_digest


def build_initial_context_snapshot_binding_with_diagnostics(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> tuple[dict[str, Any], str, str, Any]:
    """Like build_initial_context_snapshot_binding, also returning §14 diagnostics."""

    validate_guidance_for_binding(config, workspace=workspace)
    binding, diagnostics = build_context_snapshot_payload_with_diagnostics(
        config,
        workspace=workspace,
    )
    spec_digest = compute_context_spec_digest_from_config(config, workspace=workspace)
    snapshot_digest = compute_context_snapshot_digest_from_payload(binding)
    return binding, spec_digest, snapshot_digest, diagnostics


def recompute_context_snapshot_binding(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> tuple[dict[str, Any], str]:
    binding, _diagnostics = build_context_snapshot_payload_with_diagnostics(
        config,
        workspace=workspace,
        allow_missing_guidance_files=True,
    )
    return binding, compute_context_snapshot_digest_from_payload(binding)


def recompute_context_snapshot_binding_with_diagnostics(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> tuple[dict[str, Any], str, Any]:
    binding, diagnostics = build_context_snapshot_payload_with_diagnostics(
        config,
        workspace=workspace,
        allow_missing_guidance_files=True,
    )
    return binding, compute_context_snapshot_digest_from_payload(binding), diagnostics


def validate_resume_context_bindings(
    run: dict[str, Any],
    production: dict[str, Any],
    candidate_config: dict[str, Any],
    *,
    workspace: Path,
) -> str | None:
    """Read-only resume guard for context_spec and context_snapshot drift (§21 test 14)."""

    digests = run.get("digests") or {}
    if not isinstance(digests, dict):
        return "run digests missing"

    from top_down_planning.config.context import compute_context_spec_digest_from_config

    spec_digest = compute_context_spec_digest_from_config(
        candidate_config,
        workspace=workspace,
    )
    if str(digests.get("context_spec") or "") != spec_digest:
        return "context_spec digest mismatch blocks resume"

    old_binding = run.get("context_snapshot_binding")
    if not isinstance(old_binding, dict):
        return "context_snapshot_binding missing on run record"

    new_binding, new_snapshot_digest = recompute_context_snapshot_binding(
        candidate_config,
        workspace=workspace,
    )
    stored_snapshot_digest = str(digests.get("context_snapshot") or "")
    if new_snapshot_digest == stored_snapshot_digest:
        return None

    try:
        validate_production_snapshot_rebase(
            old_binding,
            new_binding,
            production,
            workspace=workspace,
        )
    except (UnauthorizedContextMutationError, InvalidProductionEvidenceError) as exc:
        return str(exc)
    return None


__all__ = [
    "InvalidProductionEvidenceError",
    "UnauthorizedContextMutationError",
    "authorized_production_workspace_paths",
    "build_initial_context_snapshot_binding",
    "build_initial_context_snapshot_binding_with_diagnostics",
    "diff_snapshot_binding_paths",
    "invalid_production_evidence_refs",
    "recompute_context_snapshot_binding",
    "recompute_context_snapshot_binding_with_diagnostics",
    "short_path_for_observability",
    "validate_production_snapshot_rebase",
    "validate_resume_context_bindings",
]
