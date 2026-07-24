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
    """Ready items sorted by priority (lower first), then manifest order."""
    status_map = workspace.status_map()
    indexed = [
        (idx, item)
        for idx, item in enumerate(workspace.items)
        if is_executable(item, status_map)
    ]
    indexed.sort(key=lambda pair: (pair[1].priority, pair[0]))
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
        raise SchedulingError(describe_idle(workspace))
    return ready[0]


def describe_idle(workspace: Workspace) -> str:
    """Explain why no item is executable (for console feedback)."""
    if not workspace.items:
        return "No executable items: manifest has no items."

    status_map = workspace.status_map()
    if list_ready(workspace):
        raise RuntimeError("describe_idle called while executable items exist")

    done_count = sum(1 for item in workspace.items if item.status == ItemStatus.DONE)
    if done_count == len(workspace.items):
        return f"No executable items: all {done_count} item(s) done."

    parts: list[str] = ["No executable items"]
    in_progress = [
        item.id for item in workspace.items if item.status == ItemStatus.IN_PROGRESS
    ]
    if in_progress:
        joined = ", ".join(in_progress)
        parts.append(
            f"{len(in_progress)} in progress ({joined}) — use `todos-tool resume`"
        )

    waiting: list[str] = []
    for item in workspace.items:
        if item.status != ItemStatus.PENDING:
            continue
        if _deps_satisfied(item, status_map):
            continue
        missing = [
            dep
            for dep in item.depends_on
            if status_map.get(dep) != ItemStatus.DONE
        ]
        waiting.append(f"{item.id} (needs {', '.join(missing)})")
    if waiting:
        parts.append(f"waiting on dependencies: {'; '.join(waiting)}")

    blocked = [item.id for item in workspace.items if item.status == ItemStatus.BLOCKED]
    if blocked:
        parts.append(f"blocked: {', '.join(blocked)}")

    superseded = [
        item.id for item in workspace.items if item.status == ItemStatus.SUPERSEDED
    ]
    if superseded and len(parts) == 1:
        parts.append(f"{len(superseded)} superseded")

    return ": ".join(parts) if len(parts) > 1 else parts[0]
