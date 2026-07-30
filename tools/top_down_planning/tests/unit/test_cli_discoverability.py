"""Tests for agent CLI discoverability (todo 16)."""

from __future__ import annotations

import json

import pytest

from core_tools.schema import validate_against_schema
from top_down_planning import schema_docs
from tests.conftest import run_cli


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


def test_completion_claim_schema_rejects_goal_met_false() -> None:
    schema = schema_docs.show_schema("completion-claim")
    issues = validate_against_schema(
        {"goal_assessment": "Not met.", "goal_met": False},
        schema,
    )
    assert issues
    assert any("const" in issue for issue in issues)


def test_focused_review_request_schema_rejects_type_kind_mismatch() -> None:
    schema = schema_docs.show_schema("focused-review-request")
    issues = validate_against_schema(
        {
            "type": "focused_plan",
            "scope": {"kind": "focused_output", "item_ids": ["item-api"]},
        },
        schema,
    )
    assert issues


def test_every_advertised_schema_loads() -> None:
    for name in schema_docs.PUBLIC_SCHEMAS:
        schema = schema_docs.show_schema(name)
        assert isinstance(schema, dict)
        assert schema.get("type") or schema.get("oneOf")
