"""Test helpers shared across unit/integration suites."""

from __future__ import annotations

from pathlib import Path

import yaml


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
        rel = data.pop("_file", f"items/{idx:03d}.yaml")
        path = todos / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        refs.append({"id": data["id"], "file": rel})
    manifest = {
        "version": 1,
        "settings": settings
        or {
            "max_attempts": 5,
            "max_session_restarts_per_phase": 2,
            "work_timeout_seconds": 30,
            "review_timeout_seconds": 30,
            "auto_commit": True,
            "stop_on_failure": True,
            "parse_error_threshold": 20,
        },
        "items": refs,
    }
    (todos / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    return todos
