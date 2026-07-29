"""Test helpers shared across unit/integration suites."""

from __future__ import annotations

from pathlib import Path

import yaml

from todos_tool.models import DEFAULT_CURSOR_MODEL


def write_todos(
    root: Path,
    items: list[dict],
    *,
    settings: dict | None = None,
) -> Path:
    todos = root / "todos"
    (todos / "items").mkdir(parents=True, exist_ok=True)
    (todos / "runs").mkdir(parents=True, exist_ok=True)
    refs = []
    for idx, item in enumerate(items, start=1):
        data = dict(item)
        if "review_policy" not in data:
            data["review_policy"] = "independent"
        rel = data.pop("_file", f"items/{idx:03d}.yaml")
        path = todos / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        refs.append({"id": data["id"], "file": rel})
    default_settings = {
        "max_attempts": 5,
        "max_session_restarts_per_phase": 2,
        "work_timeout_seconds": 30,
        "review_timeout_seconds": 30,
        "auto_commit": True,
        "stop_on_failure": True,
        "parse_error_threshold": 20,
        "model": DEFAULT_CURSOR_MODEL,
        "project_check": "pytest",
    }
    manifest = {
        "version": 1,
        "settings": {**default_settings, **(settings or {})},
        "items": refs,
    }
    (todos / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    return todos
