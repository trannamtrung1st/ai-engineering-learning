"""Dependency-safe scheduling over a loaded workspace."""

from __future__ import annotations

from todos_tool.errors import SchedulingError
from todos_tool.manifest import Workspace
from todos_tool.models import ItemStatus, TodoItem


def _deps_satisfied(item: TodoItem, status_map: dict[str, ItemStatus]) -> bool:
    return all(status_map.get(dep) == ItemStatus.DONE for dep in item.depends_on)


def is_executable(item: TodoItem, status_map: dict[str, ItemStatus]) -> bool:
    """Return True if the item can be started or resumed."""
    if item.status in (ItemStatus.BLOCKED, ItemStatus.SUPERSEDED, ItemStatus.DONE):
        return False
    if item.status not in (ItemStatus.PENDING, ItemStatus.IN_PROGRESS):
        return False
    return _deps_satisfied(item, status_map)


def readiness_rows(workspace: Workspace) -> list[dict[str, str]]:
    """Return human-readable readiness info for status display."""
    status_map = workspace.status_map()
    rows: list[dict[str, str]] = []
    for item in workspace.items:
        if item.status == ItemStatus.DONE:
            ready = "done"
        elif item.status == ItemStatus.BLOCKED:
            ready = "blocked"
        elif item.status == ItemStatus.SUPERSEDED:
            ready = "superseded"
        elif not _deps_satisfied(item, status_map):
            missing = [
                dep
                for dep in item.depends_on
                if status_map.get(dep) != ItemStatus.DONE
            ]
            ready = f"waiting:{','.join(missing)}"
        elif item.status == ItemStatus.IN_PROGRESS:
            ready = "resumable"
        elif item.status == ItemStatus.PENDING:
            ready = "ready"
        else:
            ready = item.status.value
        rows.append(
            {
                "id": item.id,
                "title": item.title,
                "status": item.status.value,
                "priority": str(item.priority),
                "ready": ready,
                "commit": _format_commit(item),
            }
        )
    return rows


def _format_commit(item: TodoItem) -> str:
    if item.result.commit_sha:
        return item.result.commit_sha[:8]
    if item.status == ItemStatus.DONE:
        return "uncommitted"
    return "-"


def list_ready(workspace: Workspace) -> list[TodoItem]:
    """Ready items in manifest order, then by priority (lower first)."""
    status_map = workspace.status_map()
    ready = [item for item in workspace.items if is_executable(item, status_map)]
    # Manifest order is primary; among same position priority is already
    # secondary via stable sort on priority.
    indexed = list(enumerate(ready))
    indexed.sort(key=lambda pair: (pair[0], pair[1].priority))
    return [item for _, item in indexed]


def next_ready(workspace: Workspace, todo_id: str | None = None) -> TodoItem:
    """Pick the next executable item, optionally constrained to todo_id."""
    ready = list_ready(workspace)
    if todo_id is not None:
        item = workspace.get(todo_id)
        if item is None:
            raise SchedulingError(f"Unknown item id: {todo_id}")
        status_map = workspace.status_map()
        if not is_executable(item, status_map):
            raise SchedulingError(
                f"Item {todo_id} is not executable "
                f"(status={item.status.value}, deps={item.depends_on})"
            )
        return item
    if not ready:
        raise SchedulingError("No executable items")
    return ready[0]
