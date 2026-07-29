"""CLI-discoverable contracts, schemas, and examples for todos-tool."""

from __future__ import annotations

import json
from typing import Any, Literal

import yaml

from todos_tool import __version__
from todos_tool.config_loader import ALLOWED_CONFIG_KEYS
from todos_tool.models import (
    ItemStatus,
    ItemType,
    Manifest,
    ManifestItemRef,
    ManifestSettings,
    TodoItem,
    validate_manifest,
    validate_todo_item,
)
from todos_tool.review_scaffold import ReviewScaffold

PUBLIC_CONTRACTS = (
    "manifest",
    "item",
    "run-config",
    "review-decision",
)


def _emit(payload: Any, *, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if fmt == "yaml":
        return yaml.safe_dump(payload, sort_keys=False)
    if fmt == "text":
        if isinstance(payload, dict) and "lines" in payload:
            return "\n".join(str(line) for line in payload["lines"]) + "\n"
        return yaml.safe_dump(payload, sort_keys=False)
    raise ValueError(f"Unsupported format: {fmt!r}")


def usage_payload() -> dict[str, Any]:
    return {
        "tool": "todos-tool",
        "version": __version__,
        "discovery": {
            "usage": "todos-tool usage [--format text|json]",
            "schema_list": "todos-tool schema list [--format text|json]",
            "schema_show": "todos-tool schema show <name> [--format text|json|yaml]",
            "example_list": "todos-tool example list [--format text|json]",
            "example_show": "todos-tool example show <name> [--format text|json|yaml]",
        },
        "commands": [
            {
                "name": "validate",
                "purpose": "Validate TODO workspace schemas and dependencies",
                "example": "todos-tool validate --workspace .",
            },
            {
                "name": "status",
                "purpose": "Show item readiness and execution state",
                "example": "todos-tool status --workspace .",
            },
            {
                "name": "run",
                "purpose": "Execute ready items in dependency-safe order",
                "example": "todos-tool run --workspace . [--config run.config.yaml]",
            },
            {
                "name": "resume",
                "purpose": "Recover from persisted state and continue",
                "example": "todos-tool resume --workspace .",
            },
            {
                "name": "commit",
                "purpose": "Commit trackable changes for a done item",
                "example": "todos-tool commit --workspace . --todo TASK-001",
            },
        ],
        "related_tools": [
            {
                "name": "todos-review-tool",
                "purpose": "Session-scoped review submission during run",
                "discovery": [
                    "todos-tool schema show review-decision",
                    "todos-tool example show review-decision",
                ],
                "workflow": [
                    "todos-review-tool scaffold",
                    "todos-review-tool validate --json '<decision>'",
                    "todos-review-tool submit --json '<decision>'",
                ],
            }
        ],
    }


def usage_text() -> dict[str, list[str]]:
    payload = usage_payload()
    lines = [
        f"{payload['tool']} {payload['version']}",
        "",
        "Discovery:",
        "  todos-tool usage [--format text|json]",
        "  todos-tool schema list",
        "  todos-tool schema show <name>",
        "  todos-tool example list",
        "  todos-tool example show <name>",
        "",
        "Commands:",
    ]
    for cmd in payload["commands"]:
        lines.append(f"  {cmd['name']:<8} {cmd['purpose']}")
        lines.append(f"           {cmd['example']}")
    lines.append("")
    lines.append("Related:")
    for tool in payload["related_tools"]:
        lines.append(f"  {tool['name']}: {tool['purpose']}")
        for command in tool.get("discovery", ()):
            lines.append(f"    {command}")
    return {"lines": lines}


def _manifest_contract() -> dict[str, Any]:
    return {
        "name": "manifest",
        "version": 1,
        "description": "TODO workspace manifest at todos/manifest.yaml",
        "authority": "todos_tool.models.validate_manifest",
        "format": "contract",
        "fields": {
            "version": "Must be 1",
            "settings": "Execution settings (see manifest-settings contract)",
            "items": "List of {id, file} references to item YAML files",
            "authority": "Optional list of authority reference strings",
            "hard_rules": "Optional list of free-form rules",
            "stop_conditions": "Optional list of stop conditions",
            "out_of_scope": "Optional list of out-of-scope notes",
            "agent_context": "Optional phase-specific skills/rules/model overrides",
            "execution_groups": "Optional [{id, members, rationale?}] atomic multi-item units",
        },
    }


def _item_contract() -> dict[str, Any]:
    return {
        "name": "item",
        "version": 1,
        "description": "Single TODO item YAML under todos/items/",
        "authority": "todos_tool.models.validate_todo_item",
        "format": "contract",
        "fields": {
            "version": "Must be 1",
            "id": "Stable item identifier",
            "title": "Short title",
            "type": "feature | fix | refactor",
            "status": "pending | in_progress | blocked | done | superseded",
            "priority": "Integer; lower runs earlier among ready items",
            "depends_on": "List of item ids that must be done first",
            "description": "Implementation description",
            "acceptance_criteria": "List of observable criteria",
            "validation": "{commands: [shell command, ...]}",
            "evidence": "{commands: [{command, cwd?, timeout_seconds?}, ...]}",
            "context": "{files: [path, ...]}",
            "checklist": "[{id, text, done}, ...] agent-owned work plan",
            "contract_refs": "Optional authority references",
            "agent_context": "Optional phase-specific skills/rules/model",
            "allow_empty_commit": "Boolean; default true",
            "review_policy": "deterministic | independent; default deterministic",
            "result": "{completed_at, commit_sha, summary}",
        },
    }


def _run_config_contract() -> dict[str, Any]:
    return {
        "name": "run-config",
        "version": 1,
        "description": "Optional YAML run config for todos-tool run/resume",
        "authority": "todos_tool.config_loader.ALLOWED_CONFIG_KEYS",
        "format": "contract",
        "allowed_keys": sorted(ALLOWED_CONFIG_KEYS),
        "notes": [
            "schema_version is not supported in run config",
            "CLI flags override config values",
        ],
    }


def _review_decision_contract() -> dict[str, Any]:
    return {
        "name": "review-decision",
        "version": 1,
        "description": "Structured review submission for todos-review-tool",
        "authority": "todos_tool.models.ReviewDecision",
        "format": "contract",
        "fields": {
            "schema_version": "Must be 1",
            "item_id": "Reviewed item id",
            "logical_attempt": "Attempt number under review",
            "decision": "pass | fail | blocked",
            "summary": "Review summary",
            "acceptance_criteria": "[{criterion, passed, evidence}, ...]",
            "validation": "Authoritative validation results copied from orchestrator",
            "evidence": "Authoritative evidence results when configured",
            "instruction_compliance": "{passed, violations}",
            "issues": "Structured or plain-string issues",
            "recommended_next_action": "mark_done | retry | block",
            "proposed_commit_message": "Required on pass when trackable changes exist",
        },
    }


def _contract_by_name(name: str) -> dict[str, Any]:
    builders = {
        "manifest": _manifest_contract,
        "item": _item_contract,
        "run-config": _run_config_contract,
        "review-decision": _review_decision_contract,
    }
    if name not in builders:
        known = ", ".join(PUBLIC_CONTRACTS)
        raise KeyError(f"Unknown contract {name!r}; known: {known}")
    return builders[name]()


def list_schemas() -> dict[str, Any]:
    return {
        "tool": "todos-tool",
        "contracts": [
            _manifest_contract(),
            _item_contract(),
            _run_config_contract(),
            _review_decision_contract(),
        ],
    }


def show_schema(name: str) -> dict[str, Any]:
    return _contract_by_name(name)


def _example_manifest() -> dict[str, Any]:
    manifest = Manifest(
        settings=ManifestSettings(max_attempts=3, model="composer-2.5"),
        items=[
            ManifestItemRef(id="TASK-001", file="items/001-feature.yaml"),
        ],
        hard_rules=["Follow repository conventions."],
    )
    payload = manifest.to_dict()
    validate_manifest(payload)
    return payload


def _example_item() -> dict[str, Any]:
    item = TodoItem(
        id="TASK-001",
        title="Add greeting helper",
        type=ItemType.FEATURE,
        status=ItemStatus.PENDING,
        description="Implement a greeting helper.",
        acceptance_criteria=[
            "A greeting helper exists and returns a non-empty string.",
        ],
        validation={"commands": ["pytest -q"]},
    )
    payload = item.to_dict()
    validate_todo_item(payload)
    return payload


def _example_run_config() -> dict[str, Any]:
    return {
        "workspace": ".",
        "todos_dir": "todos",
        "model": "composer-2.5",
        "context": {
            "files": [{"path": "AGENTS.md", "required": False}],
            "instructions": ["Follow existing architecture."],
        },
        "evidence": {"required_commands": ["pytest"]},
        "git": {"commit_prefix": "agent:"},
    }


def _example_review_decision() -> dict[str, Any]:
    scaffold = ReviewScaffold(
        schema_version=1,
        item_id="TASK-001",
        logical_attempt=1,
        acceptance_criteria=["Criterion one"],
        allow_empty_commit=True,
        authoritative_validation=[],
        authoritative_evidence=[],
    )
    return scaffold.decision_template()


def _example_by_name(name: str) -> dict[str, Any]:
    builders = {
        "manifest": _example_manifest,
        "item": _example_item,
        "run-config": _example_run_config,
        "review-decision": _example_review_decision,
    }
    if name not in builders:
        known = ", ".join(PUBLIC_CONTRACTS)
        raise KeyError(f"Unknown example {name!r}; known: {known}")
    return builders[name]()


def list_examples() -> dict[str, Any]:
    return {
        "tool": "todos-tool",
        "examples": list(PUBLIC_CONTRACTS),
    }


def show_example(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "example": _example_by_name(name),
    }


def render_usage(*, fmt: str) -> str:
    if fmt == "text":
        return _emit(usage_text(), fmt="text")
    return _emit(usage_payload(), fmt=fmt)


def render_schema_list(*, fmt: str) -> str:
    payload = list_schemas()
    if fmt == "text":
        lines = ["Contracts:"]
        for contract in payload["contracts"]:
            lines.append(
                f"  {contract['name']:<16} v{contract['version']}  {contract['description']}"
            )
        return _emit({"lines": lines}, fmt="text")
    return _emit(payload, fmt=fmt)


def render_schema_show(name: str, *, fmt: str) -> str:
    return _emit(show_schema(name), fmt=fmt)


def render_example_list(*, fmt: str) -> str:
    payload = list_examples()
    if fmt == "text":
        lines = ["Examples:"] + [f"  {name}" for name in payload["examples"]]
        return _emit({"lines": lines}, fmt="text")
    return _emit(payload, fmt=fmt)


def render_example_show(name: str, *, fmt: str) -> str:
    return _emit(show_example(name), fmt=fmt)


def format_review_schema_section(
    *,
    review_tool_command: str = "todos-review-tool",
    item_id: str,
    logical_attempt: int,
) -> str:
    return f"""## Review decision schema
Authoritative contract and example:
  todos-tool schema show review-decision
  todos-tool example show review-decision

Session workflow:
  {review_tool_command} scaffold
  {review_tool_command} validate --json '<decision>'
  {review_tool_command} submit --json '<decision>'

Required `item_id`: `{item_id}`
Required `logical_attempt`: `{logical_attempt}`"""


def format_repair_discovery_section() -> str:
    return """## Contract discovery
Authoritative TODO workspace contracts:
  todos-tool schema show manifest
  todos-tool schema show item
  todos-tool example show manifest
  todos-tool example show item"""
