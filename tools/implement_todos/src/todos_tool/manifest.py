"""Load and validate a todos/ workspace."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError

from todos_tool.errors import ValidationError
from todos_tool.models import ItemStatus, Manifest, TodoItem


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
        return self.todos_dir / item.source_file

    def runs_dir(self, item_id: str) -> Path:
        return self.todos_dir / "runs" / item_id

    def status_map(self) -> dict[str, ItemStatus]:
        return {item.id: item.status for item in self.items}


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
    todos_dir = (root / todos_dir_name).resolve()
    errors: list[str] = []

    if not todos_dir.is_dir():
        raise ValidationError([f"Todos directory not found: {todos_dir}"])

    manifest_path = todos_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise ValidationError([f"Missing manifest: {manifest_path}"])

    try:
        manifest = Manifest.model_validate(_load_yaml(manifest_path))
    except PydanticValidationError as exc:
        raise ValidationError(
            [f"manifest.yaml: {err['loc']}: {err['msg']}" for err in exc.errors()]
        ) from exc

    if not manifest.items:
        errors.append("manifest.yaml has no items")

    seen_ids: set[str] = set()
    items: list[TodoItem] = []

    for ref in manifest.items:
        if ref.id in seen_ids:
            errors.append(f"Duplicate item id in manifest: {ref.id}")
            continue
        seen_ids.add(ref.id)

        item_path = todos_dir / ref.file
        if not item_path.is_file():
            errors.append(f"Missing item file for {ref.id}: {ref.file}")
            continue

        try:
            raw = _load_yaml(item_path)
            item = TodoItem.model_validate(raw)
        except PydanticValidationError as exc:
            for err in exc.errors():
                errors.append(f"{ref.file}: {err['loc']}: {err['msg']}")
            continue
        except ValidationError as exc:
            errors.extend(exc.errors)
            continue

        if item.id != ref.id:
            errors.append(
                f"Item id mismatch: manifest has {ref.id}, file has {item.id}"
            )
        item.source_file = ref.file
        items.append(item)

    known_ids = {item.id for item in items}
    for item in items:
        for dep in item.depends_on:
            if dep not in known_ids and dep not in seen_ids:
                errors.append(f"{item.id} depends on unknown item: {dep}")
            elif dep == item.id:
                errors.append(f"{item.id} depends on itself")

    errors.extend(_detect_cycles(items))

    # Active state sanity: at most one in_progress with run state is OK;
    # invalid combos are checked at schedule time. Here ensure statuses are valid.
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
    data = item.model_dump(mode="json", exclude_none=False)
    # Keep enums as values
    data["type"] = item.type.value
    data["status"] = item.status.value
    if item.result.completed_at is not None:
        data["result"]["completed_at"] = item.result.completed_at.isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def append_manifest_item(
    workspace: Workspace,
    item_id: str,
    relative_file: str,
) -> None:
    """Append a new item reference to manifest.yaml."""
    manifest_path = workspace.todos_dir / "manifest.yaml"
    raw = _load_yaml(manifest_path)
    items = list(raw.get("items") or [])
    items.append({"id": item_id, "file": relative_file})
    raw["items"] = items
    manifest_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
