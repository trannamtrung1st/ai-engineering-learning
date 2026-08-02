"""Unit tests for project and agent_context configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.provider import StubProvider, build_agent_argv
from top_down_planning.config import (
    ALLOWED_OVERRIDE_PATHS,
    DEFAULT_CONFIG,
    build_agent_context_manifest_payload,
    build_context_spec_payload,
    build_context_snapshot_payload,
    compute_context_spec_digest_from_config,
    compute_context_snapshot_digest_from_config,
    compute_input_digest,
    compute_output_goal_digest,
    resolve_config,
    resolve_effective_role_context,
    resolve_provider_model,
    resolve_workspace,
)
from top_down_planning.config import ConfigError
from top_down_planning.orchestrator import (
    build_focused_review_package,
    build_planner_context_manifest,
    build_producer_context_manifest,
    build_whole_output_review_package,
    build_whole_plan_review_package,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, write_config, make_review_loop


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _base_config_yaml(
    *,
    input_refs: list[str] | None = None,
    output_goal: str = "Goal.",
    output_goal_file: str | None = None,
    agent_context: str = "",
) -> str:
    refs = input_refs or []
    refs_yaml = "\n".join(f"    - {ref}" for ref in refs)
    goal_line = (
        f"  output_goal_file: {output_goal_file}"
        if output_goal_file
        else f'  output_goal: "{output_goal}"'
    )
    return f"""
project:
  workspace: .
run:
  input_refs:
{refs_yaml}
{goal_line}
agent_context:
  default:
    model: auto
    resources: []
    skills: []
  planner:
    model: auto
    resources: []
    skills: []
  producer:
    model: auto
    resources: []
    skills: []
  reviewer:
    model: auto
    resources: []
    skills: []
{agent_context}
"""


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


def test_project_resources_absent_from_defaults() -> None:
    assert "resources" not in DEFAULT_CONFIG["project"]


def test_project_resources_absent_from_allowed_override_paths() -> None:
    assert "project.resources" not in ALLOWED_OVERRIDE_PATHS


def test_project_resources_rejected_in_yaml(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(
        tmp_path / "base.yaml",
        """
project:
  workspace: .
  resources:
    - README.md
run:
  output_goal: Goal.
""",
    )
    with pytest.raises(ConfigError, match="unknown config path"):
        resolve_config(config_path, cwd=workspace)


def test_project_resources_rejected_via_cli_set(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(
        tmp_path / "base.yaml",
        """
run:
  output_goal: Goal.
""",
    )
    with pytest.raises(ConfigError, match="unknown config path"):
        resolve_config(config_path, ["project.resources=[README.md]"], cwd=workspace)


def test_resolved_config_never_contains_project_resources(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    resolved = resolve_config(
        write_config(tmp_path / "base.yaml", "run:\n  output_goal: Goal.\n"),
        cwd=workspace,
    )
    assert "resources" not in resolved.get("project", {})


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
agent_context:
  default:
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
    extra = guide / "extra.md"
    extra.write_text("extra", encoding="utf-8")
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
  input_refs:
    - README.md
  output_goal: Goal.
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
      - docs/extra.md
    skills:
      - .agents/skills/top-down-planning/
""",
        ),
        cwd=workspace,
    )

    context = resolve_effective_role_context(config, "planner", workspace=workspace)
    assert context.model == "reasoning-model"
    assert [path.name for path in context.input_refs] == ["README.md"]
    assert [path.name for path in context.resources] == ["planning.md", "extra.md"]
    assert context.output_goal == "Goal."
    assert [entry.path.name for entry in context.skills] == ["SKILL.md", "SKILL.md"]

    producer = resolve_effective_role_context(config, "producer", workspace=workspace)
    assert producer.model == "default-model"
    assert [path.name for path in producer.input_refs] == ["README.md"]
    assert [path.name for path in producer.resources] == ["planning.md"]
    assert len(producer.skills) == 1


def test_role_resources_may_repeat_default_resources(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    shared_rule = workspace / ".cursor" / "rules" / "shared.mdc"
    shared_rule.parent.mkdir(parents=True)
    shared_rule.write_text("shared", encoding="utf-8")
    reviewer_rule = workspace / ".cursor" / "rules" / "reviewer.mdc"
    reviewer_rule.write_text("reviewer", encoding="utf-8")

    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  input_refs:
    - README.md
  output_goal: Goal.
agent_context:
  default:
    resources:
      - .cursor/rules/shared.mdc
  reviewer:
    resources:
      - .cursor/rules/shared.mdc
      - .cursor/rules/reviewer.mdc
""",
        ),
        cwd=workspace,
    )
    (workspace / "README.md").write_text("readme", encoding="utf-8")

    context = resolve_effective_role_context(config, "reviewer", workspace=workspace)
    assert [path.name for path in context.resources] == [
        "shared.mdc",
        "reviewer.mdc",
    ]

    spec = build_context_spec_payload(config, workspace=workspace)
    reviewer_resources = spec["roles"]["reviewer"]["resources"]
    assert reviewer_resources.count(str(shared_rule.resolve())) == 1
    assert str(reviewer_rule.resolve()) in reviewer_resources


def test_input_ref_precedence_over_supporting_resource(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    shared = workspace / "shared.md"
    shared.write_text("shared", encoding="utf-8")

    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  input_refs:
    - shared.md
  output_goal: Goal.
agent_context:
  default:
    resources:
      - shared.md
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match="must not repeat run contracts"):
        resolve_effective_role_context(config, "planner", workspace=workspace)


def test_output_goal_file_not_duplicated_as_resource(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    goal_file = workspace / "goals" / "output-goal.md"
    goal_file.parent.mkdir(parents=True)
    goal_file.write_text("Deliverable contract.", encoding="utf-8")

    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal_file: goals/output-goal.md
agent_context:
  default:
    resources:
      - goals/output-goal.md
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match="must not repeat run contracts"):
        resolve_effective_role_context(config, "planner", workspace=workspace)


def test_all_roles_receive_input_refs_and_output_goal(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = workspace / "task.md"
    task.write_text("task", encoding="utf-8")
    config = resolve_config(
        write_config(tmp_path / "base.yaml", _base_config_yaml(input_refs=["task.md"])),
        cwd=workspace,
    )

    for role in ("planner", "producer", "reviewer"):
        context = resolve_effective_role_context(config, role, workspace=workspace)
        assert [path.name for path in context.input_refs] == ["task.md"]
        assert context.output_goal == "Goal."


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


def test_planner_manifest_includes_resolved_contracts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = workspace / "task.md"
    task.write_text("task", encoding="utf-8")
    planning = workspace / "planning.md"
    planning.write_text("planning", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            _base_config_yaml(
                input_refs=["task.md"],
                agent_context="""
  planner:
    resources:
      - planning.md
""",
            ),
        ),
        cwd=workspace,
    )
    run = {"digests": {}, "workspace": str(workspace)}
    plan = type("PlanStub", (), {"output_goal": "Goal.", "revision": 0})()
    manifest = build_planner_context_manifest("run-20260101T000002-000002", run, config, plan)
    assert manifest["agent_context"]["role"] == "planner"
    assert manifest["input_refs"] == [str(task.resolve())]
    assert manifest["output_goal"] == "Goal."
    assert "input_refs" not in manifest["agent_context"]
    assert "output_goal" not in manifest["agent_context"]
    assert [str(planning.resolve())] == manifest["agent_context"]["resources"]
    protocol = " ".join(manifest["protocol_instructions"])
    assert "plan-tree decomposition" in protocol
    assert manifest["tool_instructions"]["completion_signal"] == "candidate_plan_ready"


def test_producer_manifest_includes_protocol_instructions(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(tmp_path / "base.yaml", _base_config_yaml()),
        cwd=workspace,
    )
    run = {"digests": {}, "workspace": str(workspace)}
    plan = Plan(
        id="plan-producer",
        revision=1,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )
    manifest = build_producer_context_manifest(
        "run-20260101T000003-000003",
        run,
        config,
        plan,
    )
    assert manifest["output_goal"] == "Goal."
    assert manifest["approved_plan"] is not None
    assert manifest["approved_plan"]["revision"] == 1
    assert "approved_plan_revision" not in manifest
    protocol = " ".join(manifest["protocol_instructions"])
    assert "tdp agent production" in protocol
    assert manifest["tool_instructions"]["batch_complete_signal"] == "batch_complete"


def test_reviewer_packages_include_contracts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = workspace / "task.md"
    task.write_text("task", encoding="utf-8")
    config = resolve_config(
        write_config(tmp_path / "base.yaml", _base_config_yaml(input_refs=["task.md"])),
        cwd=workspace,
    )
    run = {"digests": {}, "workspace": str(workspace)}
    plan = Plan(
        id="plan-review",
        revision=1,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )
    loop = make_review_loop(
        id="loop-1",
        type="focused_plan",
        reviewer_session_id=None,
        scope={"item_ids": ["item-root"]},
        target_revision=1,
    )
    focused = build_focused_review_package(
        "run-review",
        run,
        config,
        loop,
        plan=plan,
    )
    assert focused["input_refs"] == [str(task.resolve())]
    assert focused["output_goal"] == "Goal."

    whole_plan_loop = make_review_loop(
        id="loop-2",
        type="whole_plan",
        reviewer_session_id=None,
        scope={},
        target_revision=1,
    )
    whole_plan = build_whole_plan_review_package(
        "run-review",
        run,
        config,
        plan,
        whole_plan_loop,
    )
    assert whole_plan["input_refs"] == [str(task.resolve())]
    assert whole_plan["output_goal"] == "Goal."

    production = {
        "revision": 0,
        "output_revision": 1,
        "batches": [],
        "output_evidence": [],
        "dispositions": {},
    }
    whole_output_loop = make_review_loop(
        id="loop-3",
        type="whole_output",
        reviewer_session_id=None,
        scope={},
        target_revision=1,
    )
    whole_output = build_whole_output_review_package(
        "run-review",
        run,
        config,
        plan,
        production,
        whole_output_loop,
    )
    assert whole_output["input_refs"] == [str(task.resolve())]
    assert whole_output["output_goal"] == "Goal."


def test_context_spec_digest_stable_for_equivalent_context(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    readme = workspace / "README.md"
    readme.write_text("alpha", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - README.md
""",
        ),
        cwd=workspace,
    )
    digest_a = compute_context_spec_digest_from_config(config, workspace=workspace)
    digest_b = compute_context_spec_digest_from_config(config, workspace=workspace)
    assert digest_a == digest_b


def test_context_spec_digest_stable_when_supporting_resource_content_changes(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    readme = workspace / "README.md"
    readme.write_text("alpha", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - README.md
""",
        ),
        cwd=workspace,
    )
    before = compute_context_spec_digest_from_config(config, workspace=workspace)
    readme.write_text("beta", encoding="utf-8")
    after = compute_context_spec_digest_from_config(config, workspace=workspace)
    assert before == after


def test_context_snapshot_digest_changes_when_supporting_resource_content_changes(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    readme = workspace / "README.md"
    readme.write_text("alpha", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base-snapshot.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - README.md
""",
        ),
        cwd=workspace,
    )
    before = compute_context_snapshot_digest_from_config(config, workspace=workspace)
    readme.write_text("beta", encoding="utf-8")
    after = compute_context_snapshot_digest_from_config(config, workspace=workspace)
    assert before != after


def test_context_spec_digest_changes_when_resource_path_selection_changes(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "a.md").write_text("a", encoding="utf-8")
    (workspace / "b.md").write_text("b", encoding="utf-8")
    config_a = resolve_config(
        write_config(
            tmp_path / "a.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - a.md
""",
        ),
        cwd=workspace,
    )
    config_b = resolve_config(
        write_config(
            tmp_path / "b.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - b.md
""",
        ),
        cwd=workspace,
    )
    digest_a = compute_context_spec_digest_from_config(config_a, workspace=workspace)
    digest_b = compute_context_spec_digest_from_config(config_b, workspace=workspace)
    assert digest_a != digest_b


def test_context_spec_digest_changes_when_resource_order_changes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "a.md").write_text("a", encoding="utf-8")
    (workspace / "b.md").write_text("b", encoding="utf-8")
    config_ab = resolve_config(
        write_config(
            tmp_path / "ab.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - a.md
      - b.md
""",
        ),
        cwd=workspace,
    )
    config_ba = resolve_config(
        write_config(
            tmp_path / "ba.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - b.md
      - a.md
""",
        ),
        cwd=workspace,
    )
    digest_ab = compute_context_spec_digest_from_config(config_ab, workspace=workspace)
    digest_ba = compute_context_spec_digest_from_config(config_ba, workspace=workspace)
    assert digest_ab != digest_ba


def test_context_spec_digest_changes_when_role_model_changes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_a = resolve_config(
        write_config(
            tmp_path / "a.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  planner:
    model: model-a
""",
        ),
        cwd=workspace,
    )
    config_b = resolve_config(
        write_config(
            tmp_path / "b.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  planner:
    model: model-b
""",
        ),
        cwd=workspace,
    )
    digest_a = compute_context_spec_digest_from_config(config_a, workspace=workspace)
    digest_b = compute_context_spec_digest_from_config(config_b, workspace=workspace)
    assert digest_a != digest_b


def test_context_snapshot_digest_changes_when_skill_content_changes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    skill_dir = workspace / ".agents" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("skill-a", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    skills:
      - .agents/skills/demo/
""",
        ),
        cwd=workspace,
    )
    before = compute_context_snapshot_digest_from_config(config, workspace=workspace)
    skill_file.write_text("skill-b", encoding="utf-8")
    after = compute_context_snapshot_digest_from_config(config, workspace=workspace)
    assert before != after


def test_context_spec_digest_stable_when_configured_resource_deleted(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    guide = workspace / "guide.md"
    guide.write_text("guide", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - guide.md
""",
        ),
        cwd=workspace,
    )
    before = compute_context_spec_digest_from_config(config, workspace=workspace)
    guide.unlink()
    after = compute_context_spec_digest_from_config(config, workspace=workspace)
    assert before == after


def test_context_spec_and_snapshot_payloads_cover_supporting_context_only(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    task = workspace / "task.md"
    task.write_text("task", encoding="utf-8")
    guide = workspace / "guide.md"
    guide.write_text("guide", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  input_refs:
    - task.md
  output_goal: Goal.
agent_context:
  default:
    resources:
      - guide.md
""",
        ),
        cwd=workspace,
    )
    spec_payload = build_context_spec_payload(config, workspace=workspace)
    planner = spec_payload["roles"]["planner"]
    assert "project_resources" not in spec_payload
    assert "input_refs" not in planner
    assert "output_goal_digest" not in planner
    assert str(guide.resolve()) in planner["resources"]
    assert "resource_digests" not in planner
    assert "skill_digests" not in planner
    allowed_role_keys = {"model", "resources", "skills", "guidance"}
    for role_name, role_payload in spec_payload["roles"].items():
        assert "resource_digests" not in role_payload, role_name
        assert "skill_digests" not in role_payload, role_name
        assert set(role_payload) <= allowed_role_keys, role_name

    snapshot_payload = build_context_snapshot_payload(config, workspace=workspace)
    assert "roles" not in snapshot_payload
    assert "resource_digests" in snapshot_payload
    assert "skill_digests" in snapshot_payload
    assert "guidance_digests" in snapshot_payload
    assert snapshot_payload["guidance_digests"] == []
    guide_paths = set(snapshot_payload["resource_digests"])
    assert "guide.md" in guide_paths
    assert "workspace" not in snapshot_payload
    assert isinstance(snapshot_payload["resource_digests"], dict)
    assert isinstance(snapshot_payload["skill_digests"], dict)


def test_context_spec_digest_stable_when_files_change_under_resource_directory(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    src = workspace / "src"
    src.mkdir()
    (src / "a.py").write_text("a1\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  producer:
    resources:
      - src/
""",
        ),
        cwd=workspace,
    )
    before = compute_context_spec_digest_from_config(config, workspace=workspace)
    (src / "a.py").write_text("a2\n", encoding="utf-8")
    (src / "b.py").write_text("new\n", encoding="utf-8")
    (src / "a.py").unlink()
    after = compute_context_spec_digest_from_config(config, workspace=workspace)
    assert before == after


def test_context_snapshot_digest_changes_when_files_change_under_resource_directory(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    src = workspace / "src"
    src.mkdir()
    (src / "a.py").write_text("a1\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base-snapshot-dir.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  producer:
    resources:
      - src/
""",
        ),
        cwd=workspace,
    )
    before = compute_context_snapshot_digest_from_config(config, workspace=workspace)
    (src / "a.py").write_text("a2\n", encoding="utf-8")
    (src / "b.py").write_text("new\n", encoding="utf-8")
    (src / "a.py").unlink()
    after = compute_context_snapshot_digest_from_config(config, workspace=workspace)
    assert before != after


def test_context_spec_digest_unchanged_when_input_ref_content_changes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = workspace / "task.md"
    task.write_text("alpha", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  input_refs:
    - task.md
  output_goal: Goal.
""",
        ),
        cwd=workspace,
    )
    before = compute_context_spec_digest_from_config(config, workspace=workspace)
    task.write_text("beta", encoding="utf-8")
    after = compute_context_spec_digest_from_config(config, workspace=workspace)
    assert before == after


def test_stub_provider_records_selected_model() -> None:
    provider = StubProvider()
    provider.script_turn(
        [
            {"type": "assistant", "text": "ok"},
            {"type": "done", "subtype": "success", "text": "ok", "is_error": False},
        ]
    )
    context = resolve_effective_role_context(
        {
            "run": {"output_goal": "Goal."},
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
    session_id = provider.start_primary_session(
        "planner",
        build_agent_context_manifest_payload(context),
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
