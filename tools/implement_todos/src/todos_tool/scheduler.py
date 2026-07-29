"""Dependency-safe scheduling over a loaded workspace."""

from __future__ import annotations

from dataclasses import dataclass

from todos_tool.errors import SchedulingError
from todos_tool.manifest import Workspace
from todos_tool.models import ExecutionGroup, ItemStatus, TodoItem


@dataclass(frozen=True)
class ExecutionUnit:
    items: list[TodoItem]
    group_id: str | None = None


def _deps_satisfied(item: TodoItem, status_map: dict[str, ItemStatus]) -> bool:
    return all(status_map.get(dep) == ItemStatus.DONE for dep in item.depends_on)


def is_executable(item: TodoItem, status_map: dict[str, ItemStatus]) -> bool:
    """Return True if the item can be started or resumed."""
    if item.status in (ItemStatus.BLOCKED, ItemStatus.SUPERSEDED, ItemStatus.DONE):
        return False
    if item.status not in (ItemStatus.PENDING, ItemStatus.IN_PROGRESS):
        return False
    return _deps_satisfied(item, status_map)


def _group_map(workspace: Workspace) -> dict[str, ExecutionGroup]:
    return {group.id: group for group in workspace.manifest.execution_groups}


def _member_group_map(workspace: Workspace) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for group in workspace.manifest.execution_groups:
        for member in group.members:
            mapping[member] = group.id
    return mapping


def validate_execution_groups(workspace: Workspace) -> None:
    """Raise SchedulingError when execution group definitions are invalid."""
    member_to_group: dict[str, str] = {}
    for group in workspace.manifest.execution_groups:
        if not group.id.strip():
            raise SchedulingError("execution group id must not be empty")
        if not group.members:
            raise SchedulingError(f"execution group {group.id} has no members")
        seen_members: set[str] = set()
        for member in group.members:
            if member in seen_members:
                raise SchedulingError(
                    f"execution group {group.id} has duplicate member {member}"
                )
            seen_members.add(member)
            if member not in workspace._by_id:
                raise SchedulingError(
                    f"execution group {group.id} references unknown item {member}"
                )
            if member in member_to_group:
                raise SchedulingError(
                    f"item {member} appears in multiple execution groups "
                    f"({member_to_group[member]} and {group.id})"
                )
            member_to_group[member] = group.id


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


def _group_ready(
    workspace: Workspace,
    group: ExecutionGroup,
    status_map: dict[str, ItemStatus],
) -> bool:
    members = [workspace.get(member_id) for member_id in group.members]
    if any(member is None for member in members):
        return False
    for member in members:
        assert member is not None
        if not is_executable(member, status_map):
            return False
    return True


def list_ready_units(workspace: Workspace) -> list[ExecutionUnit]:
    """Ready execution units: explicit groups or individual items."""
    validate_execution_groups(workspace)
    status_map = workspace.status_map()
    member_groups = _member_group_map(workspace)
    groups = _group_map(workspace)
    units: list[ExecutionUnit] = []
    seen_groups: set[str] = set()
    seen_items: set[str] = set()

    indexed = [
        (idx, item)
        for idx, item in enumerate(workspace.items)
        if is_executable(item, status_map)
    ]
    indexed.sort(key=lambda pair: (pair[1].priority, pair[0]))

    for _, item in indexed:
        group_id = member_groups.get(item.id)
        if group_id is not None:
            if group_id in seen_groups:
                continue
            group = groups[group_id]
            if not _group_ready(workspace, group, status_map):
                continue
            members = [workspace.get(member_id) for member_id in group.members]
            if any(member is None for member in members):
                continue
            units.append(
                ExecutionUnit(
                    items=[member for member in members if member is not None],
                    group_id=group_id,
                )
            )
            seen_groups.add(group_id)
            seen_items.update(group.members)
            continue
        if item.id in seen_items:
            continue
        units.append(ExecutionUnit(items=[item]))

    return units


def next_execution_unit(
    workspace: Workspace,
    todo_id: str | None = None,
) -> ExecutionUnit:
    units = list_ready_units(workspace)
    if todo_id is not None:
        item = workspace.get(todo_id)
        if item is None:
            raise SchedulingError(f"Unknown item id: {todo_id}")
        for unit in units:
            if any(member.id == todo_id for member in unit.items):
                return unit
        status_map = workspace.status_map()
        if not is_executable(item, status_map):
            raise SchedulingError(
                f"Item {todo_id} is not executable "
                f"(status={item.status.value}, deps={item.depends_on})"
            )
        raise SchedulingError(
            f"Item {todo_id} is not ready as an execution unit "
            "(group members may be waiting on each other)"
        )
    if not units:
        raise SchedulingError(describe_idle(workspace))
    return units[0]


def next_ready(workspace: Workspace, todo_id: str | None = None) -> TodoItem:
    """Pick the next executable item, optionally constrained to todo_id."""
    return next_execution_unit(workspace, todo_id).items[0]


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
