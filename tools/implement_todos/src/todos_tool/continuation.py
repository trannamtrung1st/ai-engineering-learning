"""Bounded continuation context and controlled item restructuring."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from todos_tool.errors import RestructuringError
from todos_tool.git_service import GitStatus, diff_summary, diff_text, status
from todos_tool.manifest import Workspace, append_manifest_item, load_workspace, save_item
from todos_tool.models import (
    ChecklistItem,
    ChecklistMove,
    ItemStatus,
    RestructuringProposal,
    TodoItem,
)
from todos_tool.paths import resolve_within, validate_relative_path

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
    item_paths: list[str] | None = None,
    todos_dir: str = "todos",
) -> str:
    """Build bounded continuation context for a session restart."""
    st = status(workspace_root)
    runs_prefix = f"{todos_dir}/runs/"
    scoped_paths = item_paths or [
        path for path in st.changed_paths if not path.startswith(runs_prefix)
    ]
    diff = diff_text(workspace_root, max_chars=MAX_DIFF_CHARS, paths=scoped_paths)
    stat = diff_summary(workspace_root)

    changed_lines = [f"- {p}" for p in scoped_paths[:50]] or ["- (none)"]
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
    head = max(1, limit // 3)
    tail = max(1, limit - head - 40)
    return (
        text[:head]
        + f"\n... truncated ({len(text)} chars total) ...\n"
        + text[-tail:]
    )


def load_restructure_proposal(path: Path) -> RestructuringProposal | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RestructuringProposal.model_validate(data)
    except (OSError, ValueError) as exc:
        raise RestructuringError(f"Invalid restructure proposal at {path}: {exc}") from exc


def _validate_new_item(raw: dict[str, Any], workspace: Workspace) -> tuple[TodoItem, str]:
    data = dict(raw)
    rel = data.pop("file", None) or f"items/{str(data.get('id', '')).lower()}.yaml"
    if not isinstance(rel, str):
        raise RestructuringError("new item file must be a string")
    rel_file = validate_relative_path(rel, label="new item file")
    dest = resolve_within(workspace.todos_dir, rel_file)
    if dest.exists():
        raise RestructuringError(f"Refusing to overwrite existing item file: {rel_file}")
    try:
        item = TodoItem.model_validate(data)
    except ValueError as exc:
        raise RestructuringError(f"Invalid new item: {exc}") from exc
    if workspace.get(item.id) is not None:
        raise RestructuringError(f"New item id already exists: {item.id}")
    if not item.acceptance_criteria:
        raise RestructuringError(f"New item {item.id} missing acceptance criteria")
    item.source_file = rel_file
    return item, rel_file


def _find_checklist_entry(item: TodoItem, entry_id: str) -> ChecklistItem | None:
    for entry in item.checklist:
        if entry.id == entry_id:
            return entry
    return None


def _validate_checklist_moves(
    workspace: Workspace,
    item: TodoItem,
    moves: list[ChecklistMove],
) -> list[tuple[ChecklistMove, ChecklistItem]]:
    if not moves:
        return []
    seen_move_ids: set[str] = set()
    validated: list[tuple[ChecklistMove, ChecklistItem]] = []
    for move in moves:
        if move.id in seen_move_ids:
            raise RestructuringError(
                f"Duplicate checklist_moves id in proposal: {move.id}"
            )
        seen_move_ids.add(move.id)
        if move.to_item_id == item.id:
            raise RestructuringError(
                f"checklist_moves target must differ from source item: {move.to_item_id}"
            )
        source_entry = _find_checklist_entry(item, move.id)
        if source_entry is None:
            raise RestructuringError(
                f"checklist_moves references missing checklist entry: {move.id}"
            )
        target = workspace.get(move.to_item_id)
        if target is None:
            raise RestructuringError(
                f"checklist_moves target item unknown: {move.to_item_id}"
            )
        if target.status in (ItemStatus.DONE, ItemStatus.SUPERSEDED):
            raise RestructuringError(
                f"checklist_moves target item not eligible: {move.to_item_id} "
                f"(status={target.status.value})"
            )
        if _find_checklist_entry(target, move.id) is not None:
            raise RestructuringError(
                f"checklist_moves id already exists on target item {move.to_item_id}: "
                f"{move.id}"
            )
        validated.append((move, source_entry))
    return validated


def _apply_checklist_move(
    *,
    source: TodoItem,
    target: TodoItem,
    move: ChecklistMove,
    source_entry: ChecklistItem,
) -> None:
    source.checklist = [entry for entry in source.checklist if entry.id != move.id]
    moved = ChecklistItem(
        id=move.id,
        text=move.text if move.text is not None else source_entry.text,
        done=move.done if move.done is not None else source_entry.done,
    )
    target.checklist.append(moved)


def _validate_proposal(
    workspace: Workspace,
    item: TodoItem,
    proposal: RestructuringProposal,
) -> tuple[
    list[tuple[TodoItem, str]],
    dict[str, list[str]],
    list[tuple[ChecklistMove, ChecklistItem]],
]:
    if proposal.item_id != item.id:
        raise RestructuringError(
            f"Proposal item_id {proposal.item_id} does not match active item {item.id}"
        )

    original_criteria = list(item.acceptance_criteria)
    new_entries: list[tuple[TodoItem, str]] = []
    new_ids: set[str] = set()
    for raw in proposal.new_items:
        new_item, rel_file = _validate_new_item(raw, workspace)
        if new_item.id in new_ids:
            raise RestructuringError(f"Duplicate new item id in proposal: {new_item.id}")
        new_ids.add(new_item.id)
        new_entries.append((new_item, rel_file))

    known_ids = {entry.id for entry in workspace.items} | new_ids
    pending_updates: dict[str, list[str]] = {}
    for target_id, deps in proposal.dependency_updates.items():
        if target_id != item.id and target_id not in known_ids:
            raise RestructuringError(
                f"dependency_updates target unknown item: {target_id}"
            )
        for dep in deps:
            if dep not in known_ids:
                raise RestructuringError(
                    f"dependency_updates references unknown dependency: {dep}"
                )
        pending_updates[target_id] = list(deps)

    checklist_moves = _validate_checklist_moves(workspace, item, proposal.checklist_moves)

    updated_item = item.model_copy(deep=True)
    if item.id in pending_updates:
        updated_item.depends_on = list(pending_updates[item.id])

    if not proposal.supersede and updated_item.acceptance_criteria != original_criteria:
        if _is_weakening(original_criteria, updated_item.acceptance_criteria):
            raise RestructuringError("Refusing silent weakening of acceptance criteria")

    return new_entries, pending_updates, checklist_moves


def apply_restructure_proposal(
    workspace: Workspace,
    item: TodoItem,
    proposal: RestructuringProposal,
    *,
    proposal_path: Path | None = None,
) -> Workspace:
    """Validate and apply a restructuring proposal; returns reloaded workspace."""
    new_entries, pending_updates, checklist_moves = _validate_proposal(
        workspace, item, proposal
    )

    snapshots: dict[Path, str | None] = {}
    manifest_path = workspace.todos_dir / "manifest.yaml"
    snapshots[manifest_path] = (
        manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else None
    )
    snapshots[workspace.item_path(item)] = workspace.item_path(item).read_text(
        encoding="utf-8"
    )

    snapshot_item_ids: set[str] = {item.id}
    for target_id in pending_updates:
        if target_id != item.id:
            snapshot_item_ids.add(target_id)
    for move, _ in checklist_moves:
        snapshot_item_ids.add(move.to_item_id)

    for target_id in snapshot_item_ids:
        if target_id == item.id:
            continue
        target = workspace.get(target_id)
        if target is not None:
            target_path = workspace.item_path(target)
            snapshots[target_path] = target_path.read_text(encoding="utf-8")

    created_files: list[Path] = []

    def _restore() -> None:
        for path in created_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        for path, content in snapshots.items():
            if content is None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                path.write_text(content, encoding="utf-8")

    try:
        for new_item, rel_file in new_entries:
            save_item(workspace, new_item)
            created_files.append(workspace.todos_dir / rel_file)
            append_manifest_item(workspace, new_item.id, rel_file)

        for target_id, deps in pending_updates.items():
            if target_id == item.id:
                item.depends_on = list(deps)
            else:
                target = workspace.get(target_id)
                if target is not None:
                    target.depends_on = list(deps)
                    save_item(workspace, target)

        touched_targets: dict[str, TodoItem] = {}
        for move, source_entry in checklist_moves:
            target = workspace.get(move.to_item_id)
            if target is None:
                raise RestructuringError(
                    f"checklist_moves target missing during apply: {move.to_item_id}"
                )
            _apply_checklist_move(
                source=item,
                target=target,
                move=move,
                source_entry=source_entry,
            )
            touched_targets[target.id] = target

        if proposal.supersede:
            item.status = ItemStatus.SUPERSEDED
        save_item(workspace, item)
        for target in touched_targets.values():
            if target.id != item.id:
                save_item(workspace, target)

        reloaded = load_workspace(workspace.root, workspace.todos_dir.name)

        for target_id, deps in pending_updates.items():
            target = reloaded.get(target_id)
            if target is None:
                raise RestructuringError(
                    f"dependency_updates target missing after apply: {target_id}"
                )
            if list(target.depends_on) != list(deps):
                target.depends_on = list(deps)
                save_item(reloaded, target)

        if proposal_path is not None and proposal_path.is_file():
            archive_path = proposal_path.with_suffix(".applied.json")
            shutil.move(str(proposal_path), str(archive_path))

        return load_workspace(workspace.root, workspace.todos_dir.name)
    except Exception:
        _restore()
        raise


def _is_weakening(original: list[str], updated: list[str]) -> bool:
    """True if updated drops criteria without adding replacements of equal/greater size."""
    if len(updated) < len(original):
        return True
    orig_set = {c.strip().lower() for c in original}
    new_set = {c.strip().lower() for c in updated}
    return orig_set - new_set and len(new_set) <= len(orig_set)


def snapshot_pre_existing_dirty(st: GitStatus) -> set[str]:
    return set(st.changed_paths)
