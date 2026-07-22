"""Load and validate a todos/ workspace."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from todos_tool.errors import ValidationError
from todos_tool.models import ItemStatus, Manifest, TodoItem, validate_manifest, validate_todo_item
from todos_tool.paths import resolve_within, validate_item_id, validate_relative_path


class Workspace:
    """Loaded todos workspace with validated items in manifest order."""

    def __init__(
        self,
        root: Path,
        todos_dir: Path,
        manifest: Manifest,
        items: list[TodoItem],
    ) -> None:
        self.root = root.resolve()
        self.todos_dir = todos_dir.resolve()
        self.manifest = manifest
        self.items = items
        self._by_id = {item.id: item for item in items}

    def get(self, item_id: str) -> TodoItem | None:
        return self._by_id.get(item_id)

    def item_path(self, item: TodoItem) -> Path:
        if not item.source_file:
            raise ValidationError([f"Item {item.id} has no source_file"])
        return resolve_within(self.todos_dir, item.source_file)

    def runs_dir(self, item_id: str) -> Path:
        validate_item_id(item_id)
        return resolve_within(self.todos_dir, f"runs/{item_id}")

    def status_map(self) -> dict[str, ItemStatus]:
        return {item.id: item.status for item in self.items}


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationError([f"Cannot read {path}: {exc}"]) from exc
    except yaml.YAMLError as exc:
        raise ValidationError([f"Invalid YAML in {path}: {exc}"]) from exc
    if data is None:
        raise ValidationError([f"Empty YAML file: {path}"])
    if not isinstance(data, dict):
        raise ValidationError([f"Expected mapping in {path}"])
    return data


def _detect_cycles(items: list[TodoItem]) -> list[str]:
    graph = {item.id: list(item.depends_on) for item in items}
    errors: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, stack: list[str]) -> None:
        if node in visiting:
            cycle_start = stack.index(node)
            cycle = " -> ".join(stack[cycle_start:] + [node])
            errors.append(f"Dependency cycle detected: {cycle}")
            return
        if node in visited or node not in graph:
            return
        visiting.add(node)
        stack.append(node)
        for dep in graph[node]:
            dfs(dep, stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for item_id in graph:
        dfs(item_id, [])
    return errors


def load_workspace(
    workspace_root: Path,
    todos_dir_name: str = "todos",
) -> Workspace:
    """Load and validate manifest + items under workspace_root/todos_dir_name."""
    root = workspace_root.resolve()
    try:
        todos_dir = resolve_within(root, todos_dir_name)
    except ValueError as exc:
        raise ValidationError([str(exc)]) from exc
    errors: list[str] = []

    if not todos_dir.is_dir():
        raise ValidationError([f"Todos directory not found: {todos_dir}"])

    manifest_path = todos_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise ValidationError([f"Missing manifest: {manifest_path}"])

    try:
        raw_manifest = _load_yaml(manifest_path)
        validate_manifest(raw_manifest)
        manifest = Manifest.from_dict(raw_manifest)
    except ValueError as exc:
        raise ValidationError([f"manifest.yaml: {exc}"]) from exc

    if not manifest.items:
        errors.append("manifest.yaml has no items")

    seen_ids: set[str] = set()
    manifest_ids = {ref.id for ref in manifest.items}
    items: list[TodoItem] = []

    for ref in manifest.items:
        if ref.id in seen_ids:
            errors.append(f"Duplicate item id in manifest: {ref.id}")
            continue
        seen_ids.add(ref.id)

        try:
            validate_item_id(ref.id)
            rel_file = validate_relative_path(ref.file, label="manifest item file")
            item_path = resolve_within(todos_dir, rel_file)
        except ValueError as exc:
            errors.append(f"{ref.id}: {exc}")
            continue

        if not item_path.is_file():
            errors.append(f"Missing item file for {ref.id}: {ref.file}")
            continue

        try:
            raw = _load_yaml(item_path)
            validate_todo_item(raw)
            item = TodoItem.from_dict(raw)
        except ValueError as exc:
            errors.append(f"{ref.file}: {exc}")
            continue
        except ValidationError as exc:
            errors.extend(exc.errors)
            continue

        if item.id != ref.id:
            errors.append(
                f"Item id mismatch: manifest has {ref.id}, file has {item.id}"
            )
        item.source_file = rel_file
        items.append(item)

    for item in items:
        for dep in item.depends_on:
            if dep not in manifest_ids:
                errors.append(f"{item.id} depends on unknown item: {dep}")
            elif dep == item.id:
                errors.append(f"{item.id} depends on itself")

    errors.extend(_detect_cycles(items))

    in_progress = [i.id for i in items if i.status == ItemStatus.IN_PROGRESS]
    if len(in_progress) > 1:
        errors.append(
            "Multiple items in_progress: " + ", ".join(in_progress)
            + " (resume one at a time or fix statuses)"
        )

    if errors:
        raise ValidationError(errors)

    return Workspace(root=root, todos_dir=todos_dir, manifest=manifest, items=items)


def save_item(workspace: Workspace, item: TodoItem) -> None:
    """Write an item YAML back to disk (without source_file)."""
    path = workspace.item_path(item)
    data = item.to_dict()
    if item.result.completed_at is not None:
        data["result"]["completed_at"] = item.result.completed_at.isoformat()
    _atomic_write_text(
        path,
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
    )


def append_manifest_item(
    workspace: Workspace,
    item_id: str,
    relative_file: str,
) -> None:
    """Append a new item reference to manifest.yaml."""
    validate_item_id(item_id)
    rel_file = validate_relative_path(relative_file, label="manifest item file")
    resolve_within(workspace.todos_dir, rel_file)
    manifest_path = workspace.todos_dir / "manifest.yaml"
    raw = _load_yaml(manifest_path)
    items = list(raw.get("items") or [])
    items.append({"id": item_id, "file": rel_file})
    raw["items"] = items
    _atomic_write_text(
        manifest_path,
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
    )
