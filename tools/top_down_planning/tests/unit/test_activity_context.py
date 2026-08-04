"""Activity-aware agent_context configuration contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.config import ALLOWED_OVERRIDE_PATHS, resolve_config
from top_down_planning.config.activities import (
    ACTIVITY_ROLE_MAP,
    ALLOWED_AGENT_ACTIVITIES,
    ALLOWED_AGENT_ROLES,
    assert_valid_activity_role_pair,
    agent_context_override_paths,
    role_for_activity,
)
from top_down_planning.config import ConfigError
from tests.helpers import write_config


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _nested_agent_context_yaml(*, extra: str = "") -> str:
    return f"""
run:
  output_goal: Goal.
agent_context:
  default:
    model: auto
    guidance: []
    resources: []
    skills: []
  roles:
    planner:
      resources: []
      skills: []
    producer:
      resources: []
      skills: []
    reviewer:
      resources: []
      skills: []
  activities:
    initial_plan:
      model: smart
    plan_revision:
      model: medium
    plan_amendment:
      model: smart
    production:
      model: medium
    output_revision:
      model: medium
    initial_review:
      model: smart
    finding_verification:
      model: smart
    scope_review:
      model: smart
{extra}
"""


def test_nested_agent_context_shape_resolves(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        _nested_agent_context_yaml(),
    )
    resolved = resolve_config(config_path, cwd=workspace)
    assert "roles" in resolved["agent_context"]
    assert "activities" in resolved["agent_context"]
    assert resolved["agent_context"]["activities"]["plan_revision"]["model"] == "medium"


def test_flat_agent_context_role_keys_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        """
run:
  output_goal: Goal.
agent_context:
  planner:
    model: auto
""",
    )
    with pytest.raises(ConfigError, match="unknown agent_context key"):
        resolve_config(config_path, cwd=workspace)


def test_unknown_agent_context_top_level_key_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        """
run:
  output_goal: Goal.
agent_context:
  auditor:
    model: review-model
""",
    )
    with pytest.raises(ConfigError, match="unknown agent_context key"):
        resolve_config(config_path, cwd=workspace)


def test_unknown_activity_name_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        """
run:
  output_goal: Goal.
agent_context:
  activities:
    not_an_activity:
      model: smart
""",
    )
    with pytest.raises(ConfigError, match="unknown agent_context activity"):
        resolve_config(config_path, cwd=workspace)


def test_unknown_role_name_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        """
run:
  output_goal: Goal.
agent_context:
  roles:
    auditor:
      model: smart
""",
    )
    with pytest.raises(ConfigError, match="unknown agent_context role"):
        resolve_config(config_path, cwd=workspace)


def test_activity_with_role_field_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        """
run:
  output_goal: Goal.
agent_context:
  activities:
    initial_plan:
      role: planner
      model: smart
""",
    )
    with pytest.raises(ConfigError, match="role"):
        resolve_config(config_path, cwd=workspace)


def test_unsupported_activity_field_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        """
run:
  output_goal: Goal.
agent_context:
  activities:
    initial_plan:
      escalation_model: smart
""",
    )
    with pytest.raises(ConfigError, match="unsupported"):
        resolve_config(config_path, cwd=workspace)


@pytest.mark.parametrize("activity,role", sorted(ACTIVITY_ROLE_MAP.items()))
def test_activity_role_map_pairs(activity: str, role: str) -> None:
    assert role_for_activity(activity) == role
    assert_valid_activity_role_pair(role, activity)


def test_invalid_activity_role_pair_raises() -> None:
    with pytest.raises(ValueError, match="must run as role"):
        assert_valid_activity_role_pair("producer", "initial_plan")


def test_agent_context_override_paths_cover_roles_and_activities() -> None:
    paths = agent_context_override_paths()
    assert "agent_context.roles.planner.model" in paths
    assert "agent_context.activities.plan_revision.model" in paths
    assert "agent_context.planner.model" not in paths
    assert paths <= ALLOWED_OVERRIDE_PATHS


def test_cli_set_nested_activity_model(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config_path = write_config(tmp_path / "cfg.yaml", _nested_agent_context_yaml())
    resolved = resolve_config(
        config_path,
        ["agent_context.activities.production.model=fast-model"],
        cwd=workspace,
    )
    assert resolved["agent_context"]["activities"]["production"]["model"] == "fast-model"


def test_cli_set_flat_role_path_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with pytest.raises(ConfigError, match="unknown config path"):
        resolve_config(
            None,
            ["agent_context.producer.model=gpt-4"],
            cwd=workspace,
        )


def test_defaults_include_all_roles_and_activities() -> None:
    from top_down_planning.config.defaults import DEFAULT_CONFIG

    roles = DEFAULT_CONFIG["agent_context"]["roles"]
    activities = DEFAULT_CONFIG["agent_context"]["activities"]
    assert set(roles) == ALLOWED_AGENT_ROLES
    assert set(activities) == ALLOWED_AGENT_ACTIVITIES


def test_activity_model_precedence_default_role_activity(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    model: default-model
  roles:
    planner:
      model: role-model
  activities:
    plan_revision:
      model: activity-model
""",
        ),
        cwd=workspace,
    )
    from top_down_planning.config import resolve_effective_activity_context

    context = resolve_effective_activity_context(
        config,
        "planner",
        "plan_revision",
        workspace=workspace,
    )
    assert context.model == "activity-model"
    assert context.activity == "plan_revision"
    assert context.context_digest


def test_activity_model_not_inferred_from_other_activity(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  activities:
    plan_revision:
      model: medium
    production:
      model: fast
""",
        ),
        cwd=workspace,
    )
    from top_down_planning.config import resolve_effective_activity_context

    revision = resolve_effective_activity_context(
        config,
        "planner",
        "plan_revision",
        workspace=workspace,
    )
    production = resolve_effective_activity_context(
        config,
        "producer",
        "production",
        workspace=workspace,
    )
    assert revision.model == "medium"
    assert production.model == "fast"


def test_manifest_payload_includes_activity(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(tmp_path / "cfg.yaml", _nested_agent_context_yaml()),
        cwd=workspace,
    )
    from top_down_planning.config import (
        build_agent_context_manifest_payload,
        resolve_effective_activity_context,
    )

    context = resolve_effective_activity_context(
        config,
        "planner",
        "initial_plan",
        workspace=workspace,
    )
    payload = build_agent_context_manifest_payload(context)
    assert payload["agent_context"]["activity"] == "initial_plan"
    assert payload["agent_context"]["context_digest"] == context.context_digest


def test_manifest_agent_context_fields_round_trip() -> None:
    from top_down_planning.orchestrator.agent_context import manifest_agent_context_fields

    manifest = {
        "agent_context": {
            "activity": "plan_revision",
            "context_digest": "abc123",
        }
    }
    assert manifest_agent_context_fields(manifest) == ("plan_revision", "abc123")
    assert manifest_agent_context_fields({}) == (None, None)
