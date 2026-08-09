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
    build_context_spec_payload,
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
    """Snapshot-bound drift is not authorized by production evidence."""

    def __init__(
        self,
        message: str,
        *,
        unauthorized_paths: tuple[str, ...] = (),
        changed_paths: tuple[str, ...] = (),
        authorized_changed_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.unauthorized_paths = unauthorized_paths
        self.changed_paths = changed_paths
        self.authorized_changed_paths = authorized_changed_paths


def _skill_binding_keys(binding: dict[str, Any]) -> set[str]:
    skills_raw = binding.get("skill_digests") or {}
    if isinstance(skills_raw, dict):
        return {str(path) for path in skills_raw}
    return set()


def _guidance_binding_keys(binding: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for entry in binding.get("guidance_digests") or []:
        if not isinstance(entry, dict):
            continue
        key = _guidance_digest_key(entry)
        if key:
            keys.add(key)
    return keys


def _resource_binding_keys(binding: dict[str, Any]) -> set[str]:
    resources_raw = binding.get("resource_digests") or {}
    if isinstance(resources_raw, dict):
        return {str(path) for path in resources_raw}
    return set()


def is_evidence_authorizable_binding_key(
    path: str,
    *,
    binding: dict[str, Any],
    other_binding: dict[str, Any] | None = None,
) -> bool:
    """Return whether snapshot drift on ``path`` can be authorized via outputs.

    Only resource-digest keys (workspace artifacts declared in agent resources)
    are output-authorizable. Skill and guidance binding keys are not.
    """

    bindings = [binding]
    if other_binding is not None:
        bindings.append(other_binding)
    for snapshot_binding in bindings:
        if (
            path in _skill_binding_keys(snapshot_binding)
            or path in _guidance_binding_keys(snapshot_binding)
        ):
            return False
    for snapshot_binding in bindings:
        if path in _resource_binding_keys(snapshot_binding):
            return True
    return False


def split_unauthorized_snapshot_paths(
    unauthorized_paths: tuple[str, ...] | list[str],
    *,
    binding: dict[str, Any],
    other_binding: dict[str, Any] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Partition unauthorized paths into evidence gaps vs context mutations."""

    evidence_gaps: list[str] = []
    context_mutations: list[str] = []
    for path in unauthorized_paths:
        if is_evidence_authorizable_binding_key(
            path,
            binding=binding,
            other_binding=other_binding,
        ):
            evidence_gaps.append(path)
        else:
            context_mutations.append(path)
    return tuple(evidence_gaps), tuple(context_mutations)


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
    """Every persisted evidence ref for canonicalization corruption checks."""

    refs: list[str] = []
    for entry in production.get("output_evidence") or []:
        if isinstance(entry, dict):
            ref_text = str(entry.get("ref") or "").strip()
            if ref_text:
                refs.append(ref_text)
    for batch in production.get("batches") or []:
        if not isinstance(batch, dict):
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


def latest_output_evidence_by_path(
    production: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, dict[str, Any]]:
    """Return the latest live output-evidence entry per canonical workspace path."""

    from top_down_planning.domain.production import live_output_evidence_entries

    latest: dict[str, dict[str, Any]] = {}
    for entry in live_output_evidence_entries(production):
        ref_text = str(entry.get("ref") or "").strip()
        if not ref_text:
            continue
        if not str(entry.get("snapshot_ref") or "").strip():
            continue
        try:
            canonical = canonicalize_evidence_ref(ref_text, workspace=workspace)
        except CanonicalPathError:
            continue
        latest[canonical] = dict(entry)
    return latest


def prospective_batch_output_refs(production: dict[str, Any]) -> tuple[str, ...]:
    """Output refs on the latest batch (apply candidates before artifact capture)."""

    batches = production.get("batches") or []
    if not batches:
        return ()
    last = batches[-1]
    if not isinstance(last, dict):
        return ()
    result = last.get("result")
    if not isinstance(result, dict):
        return ()
    refs: list[str] = []
    for output in result.get("outputs") or []:
        if isinstance(output, dict):
            ref = str(output.get("ref") or "").strip()
            if ref:
                refs.append(ref)
    return tuple(refs)


def authorized_production_workspace_paths(
    production: dict[str, Any],
    *,
    workspace: Path,
    prospective_output_refs: tuple[str, ...] | None = None,
) -> set[str]:
    """Canonical paths authorized by hash-matched evidence and optional apply candidates.

    Completion and resume rebase use persisted evidence only: each changed path must
    appear in the latest ``output_evidence`` entry for that path and the recorded
    sha256 must match current workspace bytes.

    ``production apply`` may pass ``prospective_output_refs`` (refs from the candidate
    batch about to be captured) so drift on those paths is authorized before capture.
    """

    from core_tools.persistence import digest_file

    authorized: set[str] = set()
    for path, entry in latest_output_evidence_by_path(
        production,
        workspace=workspace,
    ).items():
        expected = str(entry.get("sha256") or "").strip()
        if not expected:
            continue
        target = workspace / path
        if not target.is_file():
            continue
        if digest_file(target) == expected:
            authorized.add(path)
    for ref_text in prospective_output_refs or ():
        try:
            canonical = canonicalize_evidence_ref(ref_text, workspace=workspace)
        except CanonicalPathError:
            continue
        target = workspace / canonical
        if target.is_file():
            authorized.add(canonical)
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
    extra_authorized_paths: set[str] | None = None,
    prospective_output_refs: tuple[str, ...] | None = None,
) -> list[str]:
    """Authorize snapshot drift from production evidence; return changed paths."""

    changed_paths = diff_snapshot_binding_paths(old_binding, new_binding)
    if not changed_paths:
        return []

    invalid_refs = invalid_production_evidence_refs(production, workspace=workspace)
    if invalid_refs:
        raise InvalidProductionEvidenceError(invalid_refs)

    authorized = authorized_production_workspace_paths(
        production,
        workspace=workspace,
        prospective_output_refs=prospective_output_refs,
    )
    if extra_authorized_paths:
        authorized |= set(extra_authorized_paths)
    authorized_changed = [path for path in changed_paths if path in authorized]
    unauthorized = [path for path in changed_paths if path not in authorized]
    if unauthorized:
        raise UnauthorizedContextMutationError(
            format_unauthorized_mutation_message(unauthorized),
            unauthorized_paths=tuple(unauthorized),
            changed_paths=tuple(changed_paths),
            authorized_changed_paths=tuple(authorized_changed),
        )
    return changed_paths


def validate_run_production_snapshot_drift(
    run: dict[str, Any],
    config: dict[str, Any],
    production: dict[str, Any],
    *,
    workspace: Path,
    new_binding: dict[str, Any] | None = None,
    new_snapshot_digest: str | None = None,
    prospective_output_refs: tuple[str, ...] | None = None,
) -> list[str] | None:
    """Authorize cumulative production evidence for snapshot drift on a run.

    Returns changed_paths when drift exists and is fully authorized.
    Returns None when the stored context_snapshot digest is unchanged.

    Callers that already materialized the candidate binding may pass
    ``new_binding`` and ``new_snapshot_digest`` to avoid a second traversal.
    """

    old_binding = dict(run.get("context_snapshot_binding") or {})
    digests = run.get("digests") or {}
    stored_snapshot_digest = str(digests.get("context_snapshot") or "")
    if new_binding is None or new_snapshot_digest is None:
        new_binding, new_snapshot_digest = recompute_context_snapshot_binding(
            config,
            workspace=workspace,
        )
    if new_snapshot_digest == stored_snapshot_digest:
        return None
    return validate_production_snapshot_rebase(
        old_binding,
        new_binding,
        production,
        workspace=workspace,
        prospective_output_refs=prospective_output_refs,
    )


def short_path_for_observability(path: str) -> str:
    """Return canonical relative path for audit events."""

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
    """Like build_initial_context_snapshot_binding, also returning diagnostics."""

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


def _overlay_context_spec_without_model(section: Any) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {"model": None, "guidance": [], "resources": [], "skills": []}
    return {
        "model": None,
        "guidance": list(section.get("guidance") or []),
        "resources": list(section.get("resources") or []),
        "skills": list(section.get("skills") or []),
    }


def _context_spec_payload_without_models(payload: dict[str, Any]) -> dict[str, Any]:
    roles = payload.get("roles")
    activities = payload.get("activities")
    return {
        "workspace": payload.get("workspace"),
        "default": _overlay_context_spec_without_model(payload.get("default")),
        "roles": {
            str(role): _overlay_context_spec_without_model(section)
            for role, section in sorted((roles or {}).items())
        },
        "activities": {
            str(activity): _overlay_context_spec_without_model(section)
            for activity, section in sorted((activities or {}).items())
        },
        "context_snapshot": payload.get("context_snapshot"),
    }


def compute_context_spec_structural_digest_from_config(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> str:
    """Digest context spec declarations with model fields normalized away."""

    from top_down_planning.persistence.digests import digest_binding_payload

    payload = build_context_spec_payload(config, workspace=workspace)
    return digest_binding_payload(_context_spec_payload_without_models(payload))


def context_spec_diff_is_model_only(
    stored_config: dict[str, Any],
    candidate_config: dict[str, Any],
    *,
    workspace: Path,
) -> bool:
    """Return True when context-spec drift is limited to model selections."""

    stored_digest = compute_context_spec_structural_digest_from_config(
        stored_config,
        workspace=workspace,
    )
    candidate_digest = compute_context_spec_structural_digest_from_config(
        candidate_config,
        workspace=workspace,
    )
    return stored_digest == candidate_digest


def resolve_context_spec_may_change(
    *,
    run_digests: dict[str, str],
    stored_config: dict[str, Any],
    candidate_config: dict[str, Any],
    workspace: Path,
    allow_config_drift: bool,
    has_whole_plan_approval: bool,
) -> bool:
    """Return True when pre-approval resume may accept model-only context_spec drift."""

    if not allow_config_drift or has_whole_plan_approval:
        return False
    candidate_digest = compute_context_spec_digest_from_config(
        candidate_config,
        workspace=workspace,
    )
    if str(run_digests.get("context_spec") or "") == candidate_digest:
        return False
    return context_spec_diff_is_model_only(
        stored_config,
        candidate_config,
        workspace=workspace,
    )


def validate_resume_context_bindings(
    run: dict[str, Any],
    production: dict[str, Any],
    candidate_config: dict[str, Any],
    *,
    workspace: Path,
    context_spec_may_change: bool = False,
    extra_authorized_paths: set[str] | None = None,
) -> str | None:
    """Read-only resume guard for context_spec and context_snapshot drift."""

    digests = run.get("digests") or {}
    if not isinstance(digests, dict):
        return "run digests missing"

    spec_digest = compute_context_spec_digest_from_config(
        candidate_config,
        workspace=workspace,
    )
    if str(digests.get("context_spec") or "") != spec_digest and not context_spec_may_change:
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
            extra_authorized_paths=extra_authorized_paths,
        )
    except (UnauthorizedContextMutationError, InvalidProductionEvidenceError) as exc:
        return str(exc)
    return None


def sync_run_production_digests(
    store: Any,
    run_id: str,
    *,
    extra_authorized_paths: set[str] | None = None,
) -> bool:
    """Atomically refresh output and context_snapshot digests from live production."""

    from top_down_planning.persistence.digests import compute_output_digest
    from top_down_planning.workspace import run_workspace

    run = store.load_run(run_id)
    production = store.load_production(run_id)
    config = store.load_resolved_config(run_id)
    workspace = run_workspace(run)
    expected_revision = int(run["revision"])
    digests = dict(run.get("digests") or {})
    old_binding = dict(run.get("context_snapshot_binding") or {})
    old_snapshot_digest = str(digests.get("context_snapshot") or "")

    new_binding, new_snapshot_digest, _ = recompute_context_snapshot_binding_with_diagnostics(
        config,
        workspace=workspace,
    )
    snapshot_rebased = False
    if new_snapshot_digest != old_snapshot_digest:
        validate_production_snapshot_rebase(
            old_binding,
            new_binding,
            production,
            workspace=workspace,
            extra_authorized_paths=extra_authorized_paths,
        )
        snapshot_rebased = True

    run = dict(run)
    run["revision"] = expected_revision + 1
    digests["output"] = compute_output_digest(production)
    if snapshot_rebased:
        digests["context_snapshot"] = new_snapshot_digest
        run["context_snapshot_binding"] = new_binding
    run["digests"] = digests
    store.save_run(run_id, run, expected_revision)
    return snapshot_rebased


__all__ = [
    "InvalidProductionEvidenceError",
    "UnauthorizedContextMutationError",
    "authorized_production_workspace_paths",
    "build_initial_context_snapshot_binding",
    "build_initial_context_snapshot_binding_with_diagnostics",
    "context_spec_diff_is_model_only",
    "latest_output_evidence_by_path",
    "prospective_batch_output_refs",
    "resolve_context_spec_may_change",
    "diff_snapshot_binding_paths",
    "invalid_production_evidence_refs",
    "is_evidence_authorizable_binding_key",
    "recompute_context_snapshot_binding",
    "recompute_context_snapshot_binding_with_diagnostics",
    "short_path_for_observability",
    "split_unauthorized_snapshot_paths",
    "sync_run_production_digests",
    "validate_production_snapshot_rebase",
    "validate_run_production_snapshot_drift",
    "validate_resume_context_bindings",
]
