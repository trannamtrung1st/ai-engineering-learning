"""Tests for bounded YAML auto-repair."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import write_todos
from todos_tool.console_renderer import ConsoleRenderer
from todos_tool.cursor_client import CursorClient
from todos_tool.errors import TodosToolError, ValidationError
from todos_tool.manifest import load_workspace
from todos_tool.project_context import ProjectContext
from todos_tool.workspace_loader import DryRunReport, load_workspace_repairable
from todos_tool.orchestrator import RunConfig
from todos_tool.yaml_repair import (
    Recoverability,
    YamlRepairCoordinator,
    classify_validation_error,
    discover_todo_yaml_files,
    todo_yaml_content_hash,
)


def test_classify_missing_directory_not_repairable() -> None:
    exc = ValidationError(["Todos directory not found: /tmp/nope"])
    assert classify_validation_error(exc) == Recoverability.NOT_REPAIRABLE


def test_classify_yaml_syntax_repairable() -> None:
    exc = ValidationError(["Invalid YAML in manifest.yaml: mapping values are not allowed here"])
    assert classify_validation_error(exc) == Recoverability.REPAIRABLE


def test_discover_todo_yaml_files(git_project: Path, sample_item: dict) -> None:
    write_todos(git_project, [sample_item])
    paths = discover_todo_yaml_files(git_project, "todos")
    assert "todos/manifest.yaml" in paths
    assert any(path.startswith("todos/items/") for path in paths)


def test_content_hash_changes_when_yaml_changes(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    before = todo_yaml_content_hash(git_project, "todos")
    manifest = git_project / "todos" / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    after = todo_yaml_content_hash(git_project, "todos")
    assert before != after


@pytest.mark.asyncio
async def test_dry_run_report_without_repair(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    report = DryRunReport()
    config = RunConfig(workspace_root=git_project)
    ws = await load_workspace_repairable(
        config,
        allow_repair=False,
        dry_run_report=report,
    )
    assert ws.items
    assert report.repair_required is False


@pytest.mark.asyncio
async def test_dry_run_report_flags_repair_need(git_project: Path) -> None:
    todos = git_project / "todos"
    todos.mkdir(parents=True)
    (todos / "manifest.yaml").write_text("bad: [\n", encoding="utf-8")

    report = DryRunReport()
    config = RunConfig(workspace_root=git_project, dry_run=True)
    with pytest.raises(ValidationError):
        await load_workspace_repairable(
            config,
            allow_repair=False,
            dry_run_report=report,
        )
    assert report.repair_required is True
    assert report.diagnostic


@pytest.mark.asyncio
async def test_repair_fixes_malformed_manifest(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    manifest = git_project / "todos" / "manifest.yaml"
    good_text = manifest.read_text(encoding="utf-8")
    manifest.write_text("version: 1\nsettings: [\n", encoding="utf-8")

    wrapper = fake_agent.parent / "agent-repair"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        f"workspace = {str(git_project)!r}\n"
        f"good = {good_text!r}\n"
        "prompt_file = os.environ.get('TODOS_TOOL_PROMPT_FILE')\n"
        "if prompt_file and Path(prompt_file).is_file():\n"
        "    text = Path(prompt_file).read_text(encoding='utf-8')\n"
        "    if 'YAML repair session' in text:\n"
        "        (Path(workspace) / 'todos' / 'manifest.yaml').write_text(good, encoding='utf-8')\n"
        "        print('fixed yaml')\n"
        "        sys.exit(0)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    client = CursorClient(agent_bin=str(wrapper), skip_probe=True, no_color=True)
    coordinator = YamlRepairCoordinator(
        workspace_root=git_project,
        todos_dir="todos",
        client=client,
        project_context=ProjectContext.neutral(),
        resolved_context_files=[],
        renderer=ConsoleRenderer(no_color=True),
        max_attempts=2,
    )

    with pytest.raises(ValidationError):
        load_workspace(git_project)

    workspace = await coordinator.repair(
        ValidationError(["Invalid YAML in manifest.yaml: mapping values are not allowed here"])
    )
    assert workspace.items


@pytest.mark.asyncio
async def test_repair_rejects_non_todo_changes(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    manifest = git_project / "todos" / "manifest.yaml"
    manifest.write_text("version: 1\nsettings: [\n", encoding="utf-8")

    wrapper = fake_agent.parent / "agent-repair-bad"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"workspace = {str(git_project)!r}\n"
        "(Path(workspace) / 'outside.txt').write_text('nope', encoding='utf-8')\n"
        "print('touched outside')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    client = CursorClient(agent_bin=str(wrapper), skip_probe=True, no_color=True)
    coordinator = YamlRepairCoordinator(
        workspace_root=git_project,
        todos_dir="todos",
        client=client,
        project_context=ProjectContext.neutral(),
        resolved_context_files=[],
        renderer=ConsoleRenderer(no_color=True),
        max_attempts=1,
    )

    with pytest.raises(TodosToolError, match="outside TODO YAML"):
        await coordinator.repair(ValidationError(["Invalid YAML in manifest.yaml: bad"]))
