"""Unit tests for project and agent_context configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.provider import StubProvider, build_agent_argv
from top_down_planning.config import (
    ConfigError,
    build_agent_context_manifest_payload,
    compute_context_digest_from_config,
    compute_input_digest,
    compute_output_goal_digest,
    resolve_config,
    resolve_effective_role_context,
    resolve_provider_model,
    resolve_workspace,
)
from top_down_planning.orchestrator import (
    ResumeError,
    build_planner_context_manifest,
    build_producer_context_manifest,
    validate_resume_preconditions,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, write_config


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_project_workspace_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    resolved = resolve_config(None)
    assert resolve_workspace(resolved, cwd=tmp_path) == tmp_path.resolve()
    assert resolved["project"]["workspace"] == str(tmp_path.resolve())


def test_project_workspace_relative_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = tmp_path / "work"
    nested = cwd / "nested"
    nested.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    config_path = write_config(
        tmp_path / "base.yaml",
        """
project:
  workspace: nested
run:
  output_goal: Goal.
""",
    )
    resolved = resolve_config(config_path, cwd=cwd)
    assert resolve_workspace(resolved, cwd=cwd) == nested.resolve()
    assert resolved["project"]["workspace"] == str(nested.resolve())


def test_run_workspace_rejected(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        """
run:
  workspace: nested
  output_goal: Goal.
""",
    )
    with pytest.raises(ConfigError, match="unknown config path"):
        resolve_config(config_path)


def test_unknown_agent_context_role_rejected(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        """
run:
  output_goal: Goal.
agent_context:
  auditor:
    model: review-model
""",
    )
    with pytest.raises(ConfigError, match="unknown agent_context role"):
        resolve_config(config_path)


def test_path_escape_outside_workspace_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
project:
  workspace: .
  resources:
    - ../outside.txt
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match="outside project workspace"):
        resolve_effective_role_context(config, "planner", workspace=workspace)


def test_effective_context_inheritance_and_ordering(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    readme = workspace / "README.md"
    readme.write_text("readme", encoding="utf-8")
    guide = workspace / "docs"
    guide.mkdir()
    planning = guide / "planning.md"
    planning.write_text("plan", encoding="utf-8")
    common_skill_dir = workspace / ".agents" / "skills" / "common"
    common_skill_dir.mkdir(parents=True)
    (common_skill_dir / "SKILL.md").write_text("common skill", encoding="utf-8")
    planner_skill_dir = workspace / ".agents" / "skills" / "top-down-planning"
    planner_skill_dir.mkdir(parents=True)
    (planner_skill_dir / "SKILL.md").write_text("planner skill", encoding="utf-8")

    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
project:
  workspace: .
  resources:
    - README.md
agent_context:
  default:
    model: default-model
    resources:
      - docs/planning.md
    skills:
      - .agents/skills/common/
  planner:
    model: reasoning-model
    resources:
      - README.md
    skills:
      - .agents/skills/top-down-planning/
""",
        ),
        cwd=workspace,
    )

    context = resolve_effective_role_context(config, "planner", workspace=workspace)
    assert context.model == "reasoning-model"
    assert [path.name for path in context.resources] == ["README.md", "planning.md"]
    assert [entry.path.name for entry in context.skills] == ["SKILL.md", "SKILL.md"]

    producer = resolve_effective_role_context(config, "producer", workspace=workspace)
    assert producer.model == "default-model"
    assert [path.name for path in producer.resources] == ["README.md", "planning.md"]
    assert len(producer.skills) == 1


def test_model_auto_omits_provider_model(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  planner:
    model: auto
""",
        ),
        cwd=workspace,
    )
    assert resolve_provider_model(config, "planner") is None


def test_missing_skill_file_raises(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  planner:
    skills:
      - missing-skill/
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match="not found"):
        resolve_effective_role_context(config, "planner", workspace=workspace)


def test_planner_manifest_includes_agent_context(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    readme = workspace / "README.md"
    readme.write_text("readme", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
project:
  resources:
    - README.md
""",
        ),
        cwd=workspace,
    )
    run = {
        "digests": {},
        "workspace": str(workspace),
    }
    plan = type(
        "PlanStub",
        (),
        {"output_goal": "Goal.", "revision": 0},
    )()
    manifest = build_planner_context_manifest("run-20260101T000002-000002", run, config, plan)
    assert manifest["agent_context"]["role"] == "planner"
    assert any(path.endswith("README.md") for path in manifest["agent_context"]["resources"])
    protocol = " ".join(manifest["protocol_instructions"])
    assert "plan-tree decomposition" in protocol
    assert "tdp agent plan" in protocol
    assert "host planning modes" in protocol
    assert manifest["tool_instructions"]["completion_signal"] == "candidate_plan_ready"


def test_producer_manifest_includes_protocol_instructions(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
""",
        ),
        cwd=workspace,
    )
    run = {
        "digests": {},
        "workspace": str(workspace),
    }
    plan = type(
        "PlanStub",
        (),
        {"output_goal": "Goal.", "revision": 1},
    )()
    manifest = build_producer_context_manifest(
        "run-20260101T000003-000003",
        run,
        config,
        plan,
        plan_revision=1,
    )
    protocol = " ".join(manifest["protocol_instructions"])
    assert "tdp agent production" in protocol
    assert "host planning modes" in protocol
    assert manifest["tool_instructions"]["batch_complete_signal"] == "batch_complete"


def test_context_digest_persisted_and_blocks_resume_on_change(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    readme = workspace / "README.md"
    readme.write_text("alpha", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
project:
  resources:
    - README.md
""",
        ),
        cwd=workspace,
    )
    store = FileRunStore(tmp_path / "runs")
    store.root.mkdir(parents=True)
    plan_payload = {
        "schema_version": 1,
        "id": "plan-context-test",
        "revision": 0,
        "output_goal": "Goal.",
        "items": [],
    }
    store.create_run(
        "run-20260101T002301-002301",
        plan=plan_payload,
        **create_run_kwargs(workspace, resolved_config=config),
    )

    readme.write_text("beta", encoding="utf-8")
    with pytest.raises(ResumeError, match="context digest mismatch"):
        validate_resume_preconditions(store, "run-20260101T002301-002301")


def test_stub_provider_records_selected_model() -> None:
    provider = StubProvider()
    provider.script_turn(
        [
            {"type": "assistant", "text": "ok"},
            {"type": "done", "subtype": "success", "text": "ok", "is_error": False},
        ]
    )
    session_id = provider.start_primary_session(
        "planner",
        build_agent_context_manifest_payload(
            resolve_effective_role_context(
                {
                    "agent_context": {
                        "default": {"resources": [], "skills": []},
                        "planner": {"model": "reasoning-model", "resources": [], "skills": []},
                        "producer": {"resources": [], "skills": []},
                        "reviewer": {"resources": [], "skills": []},
                    },
                },
                "planner",
                workspace=Path.cwd(),
            )
        ),
        model="reasoning-model",
    )
    assert provider.get_session_reference(session_id)["model"] == "reasoning-model"


def test_build_agent_argv_uses_explicit_session_model_only(tmp_path: Path) -> None:
    argv = build_agent_argv(
        {},
        binary="/fake/agent",
        workspace=tmp_path,
        model="session-model",
    )
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "session-model"

    argv_auto = build_agent_argv(
        {},
        binary="/fake/agent",
        workspace=tmp_path,
        model="auto",
    )
    assert "--model" not in argv_auto

    argv_none = build_agent_argv(
        {},
        binary="/fake/agent",
        workspace=tmp_path,
    )
    assert "--model" not in argv_none
