"""Bounded continuation context and controlled item restructuring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from todos_tool.errors import RestructuringError
from todos_tool.git_service import GitStatus, diff_summary, diff_text, status
from todos_tool.manifest import Workspace, append_manifest_item, load_workspace, save_item
from todos_tool.models import (
    ItemStatus,
    RestructuringProposal,
    TodoItem,
)

MAX_DIFF_CHARS = 8_000
MAX_SUMMARY_CHARS = 2_000
MAX_STATUS_CHARS = 2_000


def build_continuation_context(
    *,
    item: TodoItem,
    logical_attempt: int,
    phase: str,
    workspace_root: Path,
    previous_summary: str | None,
    failure_reason: str,
    validation_notes: str | None = None,
) -> str:
    """Build bounded continuation context for a session restart."""
    st = status(workspace_root)
    diff = diff_text(workspace_root, max_chars=MAX_DIFF_CHARS)
    stat = diff_summary(workspace_root)

    changed_lines = [f"- {p}" for p in st.changed_paths[:50]] or ["- (none)"]
    parts = [
        f"Item: {item.id} ({item.title})",
        f"Logical attempt: {logical_attempt}",
        f"Phase: {phase}",
        f"Failure reason: {_truncate(failure_reason, 500)}",
        "",
        "Acceptance criteria:",
        *[f"- {c}" for c in item.acceptance_criteria],
        "",
        "Git status:",
        _truncate(st.porcelain or "(clean)", MAX_STATUS_CHARS),
        "",
        "Diff stat:",
        _truncate(stat or "(none)", 1_000),
        "",
        "Changed files:",
        *changed_lines,
        "",
        "Diff summary (bounded):",
        _truncate(diff or "(none)", MAX_DIFF_CHARS),
        "",
        "Previous session summary:",
        _truncate(previous_summary or "(none)", MAX_SUMMARY_CHARS),
    ]
    if validation_notes:
        parts.extend(
            [
                "",
                "Known validation results:",
                _truncate(validation_notes, MAX_SUMMARY_CHARS),
            ]
        )
    parts.extend(
        [
            "",
            "Instructions:",
            "- Inspect the current tree and preserve valid existing work.",
            "- Continue the same phase; do not restart from scratch unless necessary.",
            "- Do not commit or mark the item done.",
        ]
    )
    return "\n".join(parts)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... truncated ({len(text)} chars total)"


def load_restructure_proposal(path: Path) -> RestructuringProposal | None:
    if not path.is_file():
        return None
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return RestructuringProposal.model_validate(data)
    except (OSError, ValueError, PydanticValidationError) as exc:
        raise RestructuringError(f"Invalid restructure proposal at {path}: {exc}") from exc


def apply_restructure_proposal(
    workspace: Workspace,
    item: TodoItem,
    proposal: RestructuringProposal,
) -> Workspace:
    """Validate and apply a restructuring proposal; returns reloaded workspace."""
    if proposal.item_id != item.id:
        raise RestructuringError(
            f"Proposal item_id {proposal.item_id} does not match active item {item.id}"
        )

    original_criteria = list(item.acceptance_criteria)
    created_files: list[Path] = []

    try:
        for raw in proposal.new_items:
            new_item = _validate_new_item(raw, workspace)
            # Prevent weakening: new items must not empty-out original AC without supersede
            rel = raw.get("file") or f"items/{new_item.id.lower()}.yaml"
            if not isinstance(rel, str):
                raise RestructuringError("new item file must be a string")
            dest = workspace.todos_dir / rel
            if dest.exists():
                raise RestructuringError(f"Refusing to overwrite existing item file: {rel}")
            new_item.source_file = rel
            save_item(workspace, new_item)
            created_files.append(dest)
            append_manifest_item(workspace, new_item.id, rel)

        if proposal.dependency_updates:
            for target_id, deps in proposal.dependency_updates.items():
                target = workspace.get(target_id)
                if target is None and target_id != item.id:
                    # May be a newly added item — reload later
                    continue
                if target_id == item.id:
                    item.depends_on = list(deps)
                elif target is not None:
                    target.depends_on = list(deps)
                    save_item(workspace, target)

        if proposal.supersede:
            item.status = ItemStatus.SUPERSEDED
            save_item(workspace, item)
        else:
            # Reject silent AC weakening on the active item via proposal side-effects
            if item.acceptance_criteria != original_criteria:
                # Only allow AC changes if explicitly present and not a strict subset shrink
                if _is_weakening(original_criteria, item.acceptance_criteria):
                    raise RestructuringError(
                        "Refusing silent weakening of acceptance criteria"
                    )
            save_item(workspace, item)

        # Reload and validate full graph
        reloaded = load_workspace(workspace.root, workspace.todos_dir.name)
        return reloaded
    except Exception:
        for path in created_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _validate_new_item(raw: dict[str, Any], workspace: Workspace) -> TodoItem:
    data = dict(raw)
    data.pop("file", None)
    try:
        item = TodoItem.model_validate(data)
    except PydanticValidationError as exc:
        raise RestructuringError(f"Invalid new item: {exc}") from exc
    if workspace.get(item.id) is not None:
        raise RestructuringError(f"New item id already exists: {item.id}")
    if not item.acceptance_criteria:
        raise RestructuringError(f"New item {item.id} missing acceptance criteria")
    return item


def _is_weakening(original: list[str], updated: list[str]) -> bool:
    """True if updated drops criteria without adding replacements of equal/greater size."""
    if len(updated) < len(original):
        return True
    orig_set = {c.strip().lower() for c in original}
    new_set = {c.strip().lower() for c in updated}
    return orig_set - new_set and len(new_set) <= len(orig_set)


def snapshot_pre_existing_dirty(st: GitStatus) -> set[str]:
    return set(st.changed_paths)
