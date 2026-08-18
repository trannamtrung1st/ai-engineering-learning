"""Tests for agent CLI discoverability (todo 16)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from core_tools.schema import validate_against_schema
from top_down_planning import schema_docs
from top_down_planning.domain.review_policy import FINDING_CATEGORY_ORDER
from top_down_planning.domain.review_rule_registry import KNOWN_RULE_IDS
from tests.conftest import run_cli


def test_agent_readme_documents_finding_categories() -> None:
    readme = schema_docs.AGENT_README_TEXT.lower()
    assert "## review finding categories" in readme
    assert "category_definitions" in readme
    assert "rubric themes are not finding categories" in readme
    for category in FINDING_CATEGORY_ORDER:
        assert category in readme


def test_agent_readme_documents_finding_families() -> None:
    readme = schema_docs.AGENT_README_TEXT.lower()
    assert "## finding families" in readme
    assert "candidate_refs" in readme
    assert "target_finding_ids" in readme
    assert "reopens_family_id" in readme
    assert "built-in finding-family rule_id values" in readme
    assert "audit attestation" in readme
    assert "review-respond-family-discovery" in readme
    assert "review-respond-scope" in readme
    assert "review-respond-initial-approved" not in readme


def test_agent_readme_documents_audit_attestation() -> None:
    readme = schema_docs.AGENT_README_TEXT.lower()
    assert "## audit attestation" in readme
    assert "required_audit_passes" in readme
    assert "rubric_items" in readme
    assert "do not copy rubric" in readme


def test_agent_readme_documents_builtin_rule_ids() -> None:
    readme = schema_docs.AGENT_README_TEXT
    assert "## Built-in finding-family rule_id" in readme
    for rule_id in KNOWN_RULE_IDS:
        assert rule_id in readme


def test_family_discovery_example_describes_adapting_rubric_ids() -> None:
    example = schema_docs.show_example("review-respond-family-discovery")
    desc = example["description"].lower()
    assert "rubric_items" in desc
    assert "required_audit_passes" in desc


def test_family_discovery_example_uses_default_config_rubric_ids() -> None:
    example = schema_docs.show_example("review-respond-family-discovery")
    passes = example["payload"]["audit_attestation"]["passes"]
    rubric_ids = {rid for pass_item in passes for rid in pass_item["rubric_item_ids"]}
    assert "rubric-1-example" not in rubric_ids
    assert rubric_ids
    assert all(rid.startswith("rubric-") for rid in rubric_ids)


def test_builtin_rule_descriptions_cover_known_rule_ids() -> None:
    from top_down_planning.domain.review_rule_registry import (
        BUILTIN_RULE_DESCRIPTIONS,
        KNOWN_RULE_IDS,
    )

    assert set(BUILTIN_RULE_DESCRIPTIONS) == set(KNOWN_RULE_IDS)


def test_agent_help_points_to_finding_categories() -> None:
    assert "category_definitions" in schema_docs.AGENT_HELP_TEXT


def test_agent_help_includes_start_here_and_role_skills() -> None:
    help_text = schema_docs.AGENT_HELP_TEXT.lower()
    assert "start here" in help_text
    assert "auto-injected" in help_text or "bundled_skills" in help_text
    assert "tools/top_down_planning/docs/readme.md" in help_text


def test_agent_readme_documents_plan_apply_dependencies() -> None:
    readme = schema_docs.AGENT_README_TEXT.lower()
    assert "## plan apply: dependencies" in readme
    assert "expand-branch" in readme
    assert "unique" in readme and "temp_id" in readme
    assert "agent_context.skills" in readme


def test_expand_branch_example_uses_inline_depends_on() -> None:
    example = schema_docs.show_example("expand-branch")
    operations = example["payload"]["operations"]
    op_names = [op["op"] for op in operations]
    assert "add_dependency" not in op_names
    ui_op = next(op for op in operations if op.get("temp_id") == "item-ui")
    assert ui_op["item"]["depends_on"] == ["item-api"]


def test_review_finding_schema_uses_builtin_category_enum() -> None:
    schema = schema_docs.show_schema("review-respond")
    finding_schemas: list[dict[str, Any]] = []
    for branch in schema["oneOf"]:
        reported = (
            branch.get("properties", {})
            .get("reported_findings", {})
            .get("items")
        )
        if reported is not None:
            finding_schemas.append(reported)
        side_effects = (
            branch.get("properties", {})
            .get("new_direct_side_effect_findings", {})
            .get("items")
        )
        if side_effects is not None:
            finding_schemas.append(side_effects)
    assert finding_schemas
    expected = list(FINDING_CATEGORY_ORDER)
    for finding_schema in finding_schemas:
        assert finding_schema["properties"]["category"]["enum"] == expected


def test_review_respond_schema_rejects_invalid_finding_category() -> None:
    example = schema_docs.show_example("review-respond")
    payload = dict(example["payload"])
    payload["reported_findings"] = [
        {
            "id": "finding-001",
            "severity": "major",
            "category": "style",
            "target_refs": ["item-api"],
            "issue": "Bad category.",
            "recommended_change": "Use a built-in category.",
            "status": "unresolved",
        }
    ]
    issues = validate_against_schema(
        payload,
        schema_docs.show_schema("review-respond"),
    )
    assert issues


def test_add_dependency_schema_accepts_single_element_array() -> None:
    issues = validate_against_schema(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "add_dependency",
                    "item_id": "item-second",
                    "depends_on": ["item-first"],
                }
            ],
        },
        schema_docs.show_schema("plan-transaction"),
    )
    assert issues == []


def test_agent_help_lists_core_verbs() -> None:
    result = run_cli(["agent", "help"])
    assert result.exit_code == 0
    for token in (
        "plan apply",
        "production apply",
        "review respond",
        "review request",
        "schema",
        "example",
    ):
        assert token in result.stdout


def test_bare_agent_command_shows_help() -> None:
    result = run_cli(["agent"])
    assert result.exit_code == 0
    assert "tdp agent schema" in result.stdout


def test_agent_readme_command() -> None:
    result = run_cli(["agent", "readme"])
    assert result.exit_code == 0
    assert "agent protocol" in result.stdout.lower()
    assert "tdp agent schema" in result.stdout


def test_schema_list_and_show() -> None:
    listed = run_cli(["agent", "schema"])
    assert listed.exit_code == 0
    payload = listed.json()
    assert payload["ok"] is True
    names = [entry["name"] for entry in payload["schemas"]]
    assert names == list(schema_docs.PUBLIC_SCHEMAS)

    for name in schema_docs.PUBLIC_SCHEMAS:
        shown = run_cli(["agent", "schema", name])
        assert shown.exit_code == 0
        body = shown.json()
        assert body["ok"] is True
        assert body["name"] == name
        assert body["schema"]["$schema"].startswith("https://json-schema.org/")


def test_unknown_schema_lists_available_names() -> None:
    result = run_cli(["agent", "schema", "missing"])
    assert result.exit_code == 0
    payload = result.json()
    assert payload["ok"] is False
    assert payload["available"] == list(schema_docs.PUBLIC_SCHEMAS)


def test_unknown_example_lists_available_names() -> None:
    result = run_cli(["agent", "example", "missing"])
    assert result.exit_code == 0
    payload = result.json()
    assert payload["ok"] is False
    assert payload["available"] == list(schema_docs.PUBLIC_EXAMPLES)


def test_example_list_and_show() -> None:
    listed = run_cli(["agent", "example"])
    assert listed.exit_code == 0
    payload = listed.json()
    assert payload["ok"] is True
    names = [entry["name"] for entry in payload["examples"]]
    assert names == list(schema_docs.PUBLIC_EXAMPLES)

    for name in schema_docs.PUBLIC_EXAMPLES:
        shown = run_cli(["agent", "example", name])
        assert shown.exit_code == 0
        body = shown.json()
        assert body["ok"] is True
        assert body["name"] == name
        assert "payload" in body


def test_examples_validate_against_schemas() -> None:
    for name in schema_docs.PUBLIC_EXAMPLES:
        issues = schema_docs.validate_example(name)
        assert issues == [], f"{name} failed validation: {issues}"


def test_default_config_validates_against_config_schema() -> None:
    issues = validate_against_schema(
        schema_docs.default_config_example(),
        schema_docs.show_schema("config"),
    )
    assert issues == []


def test_completion_claim_schema_rejects_goal_met_field() -> None:
    schema = schema_docs.show_schema("completion-claim")
    issues = validate_against_schema(
        {"goal_assessment": "Done.", "goal_met": True, "production_revision": 0},
        schema,
    )
    assert issues
    assert any("unexpected properties" in issue for issue in issues)


def test_focused_review_request_schema_rejects_scope_kind() -> None:
    schema = schema_docs.show_schema("focused-review-request")
    issues = validate_against_schema(
        {
            "type": "focused_plan",
            "scope": {"kind": "focused_plan", "item_ids": ["item-api"]},
            "target_revision": 0,
            "target_digest": "digest",
        },
        schema,
    )
    assert issues
    assert any("unexpected properties" in issue or "oneOf" in issue for issue in issues)


def test_every_advertised_schema_loads() -> None:
    for name in schema_docs.PUBLIC_SCHEMAS:
        schema = schema_docs.show_schema(name)
        assert isinstance(schema, dict)
        assert schema.get("type") or schema.get("oneOf")
