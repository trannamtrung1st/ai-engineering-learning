"""CLI-discoverable contracts, schemas, and examples for top-down-planning."""

from __future__ import annotations

import json
from typing import Any, Literal

import yaml
from pydantic import TypeAdapter

from top_down_planning import __version__
from top_down_planning.config_loader import RunConfigFile
from top_down_planning.models import (
    AgentResponse,
    FinalConfirmationResult,
    MarkActionableOperation,
    PlanItem,
    PlanState,
    PlanningOperation,
    RenderBatchReviewResult,
    RenderedOutputReviewResult,
    SourceMetadata,
    UpdateItemOperation,
    WholePlanReviewResult,
)

PUBLIC_CONTRACTS = (
    "config",
    "plan",
    "operation",
    "transaction",
    "review-whole-plan",
    "review-final-confirmation",
    "review-render-batch",
    "review-rendered-output",
)

REVIEW_STAGES = (
    "whole_plan_review",
    "final_confirmation",
    "render_batch_review",
    "rendered_output_review",
)

_OPERATION_ADAPTER = TypeAdapter(PlanningOperation)
_UPDATE_ADAPTER = TypeAdapter(UpdateItemOperation)
_TRANSACTION_ADAPTER = TypeAdapter(AgentResponse)
_WHOLE_PLAN_REVIEW_ADAPTER = TypeAdapter(WholePlanReviewResult)
_FINAL_CONFIRMATION_ADAPTER = TypeAdapter(FinalConfirmationResult)
_RENDER_BATCH_REVIEW_ADAPTER = TypeAdapter(RenderBatchReviewResult)
_RENDERED_OUTPUT_REVIEW_ADAPTER = TypeAdapter(RenderedOutputReviewResult)
_CONFIG_ADAPTER = TypeAdapter(RunConfigFile)
_PLAN_ADAPTER = TypeAdapter(PlanState)

_PLAN_DIGEST = "a" * 64
_INPUT_DIGEST = "b" * 64
_OUTPUT_GOAL_DIGEST = "c" * 64


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
        "tool": "top-down-planning",
        "version": __version__,
        "discovery": {
            "usage": "top-down-planning usage [--format text|json]",
            "schema_list": "top-down-planning schema list [--format text|json]",
            "schema_show": "top-down-planning schema show <name> [--format text|json|yaml]",
            "example_list": "top-down-planning example list [--format text|json]",
            "example_show": "top-down-planning example show <name> [--format text|json|yaml]",
        },
        "commands": [
            {
                "name": "run",
                "purpose": "Decompose input and render deliverables",
                "example": "top-down-planning run --input idea.md --output-goal '...' --output ./out",
            }
        ],
        "related_tools": [
            {
                "name": "planning-plan-tool",
                "purpose": "Session-scoped planning operation recording",
                "discovery": [
                    "planning-plan-tool usage",
                    "planning-plan-tool schema",
                    "planning-plan-tool example",
                    "planning-plan-tool validate --json '<operation>'",
                ],
            },
            {
                "name": "planning-review-tool",
                "purpose": "Session-scoped review/confirmation results",
                "discovery": [
                    "planning-review-tool usage",
                    "planning-review-tool schema --stage whole_plan_review",
                    "planning-review-tool example --stage whole_plan_review",
                    "planning-review-tool validate --json '<result>' --stage whole_plan_review",
                ],
            },
        ],
    }


def usage_text() -> dict[str, list[str]]:
    payload = usage_payload()
    lines = [
        f"{payload['tool']} {payload['version']}",
        "",
        "Discovery:",
        "  top-down-planning usage [--format text|json]",
        "  top-down-planning schema list",
        "  top-down-planning schema show <name>",
        "  top-down-planning example list",
        "  top-down-planning example show <name>",
        "",
        "Commands:",
    ]
    for cmd in payload["commands"]:
        lines.append(f"  {cmd['name']:<8} {cmd['purpose']}")
        lines.append(f"           {cmd['example']}")
    lines.append("")
    lines.append("Related tools:")
    for tool in payload["related_tools"]:
        lines.append(f"  {tool['name']}: {tool['purpose']}")
    return {"lines": lines}


def _contract_meta(name: str, *, description: str, authority: str, version: int = 1) -> dict[str, Any]:
    return {
        "name": name,
        "version": version,
        "description": description,
        "authority": authority,
        "format": "json-schema",
    }


def _schema_for(name: str) -> dict[str, Any]:
    if name == "config":
        return {**_contract_meta("config", description="Planning run YAML config", authority="top_down_planning.config_loader.RunConfigFile"), "schema": _CONFIG_ADAPTER.json_schema()}
    if name == "plan":
        return {**_contract_meta("plan", description="Persisted planning state plan.yaml", authority="top_down_planning.models.PlanState"), "schema": _PLAN_ADAPTER.json_schema()}
    if name == "operation":
        return {**_contract_meta("operation", description="Single planning operation for planning-plan-tool", authority="top_down_planning.models.PlanningOperation"), "schema": _OPERATION_ADAPTER.json_schema()}
    if name == "transaction":
        return {**_contract_meta("transaction", description="Finalized planning transaction", authority="top_down_planning.models.AgentResponse"), "schema": _TRANSACTION_ADAPTER.json_schema()}
    if name == "review-whole-plan":
        return {**_contract_meta("review-whole-plan", description="Whole-plan review result", authority="top_down_planning.models.WholePlanReviewResult"), "schema": _WHOLE_PLAN_REVIEW_ADAPTER.json_schema()}
    if name == "review-final-confirmation":
        return {**_contract_meta("review-final-confirmation", description="Final confirmation result", authority="top_down_planning.models.FinalConfirmationResult"), "schema": _FINAL_CONFIRMATION_ADAPTER.json_schema()}
    if name == "review-render-batch":
        return {**_contract_meta("review-render-batch", description="Render batch review result", authority="top_down_planning.models.RenderBatchReviewResult"), "schema": _RENDER_BATCH_REVIEW_ADAPTER.json_schema()}
    if name == "review-rendered-output":
        return {**_contract_meta("review-rendered-output", description="Rendered output review result", authority="top_down_planning.models.RenderedOutputReviewResult"), "schema": _RENDERED_OUTPUT_REVIEW_ADAPTER.json_schema()}
    known = ", ".join(PUBLIC_CONTRACTS)
    raise KeyError(f"Unknown contract {name!r}; known: {known}")


def list_schemas() -> dict[str, Any]:
    return {
        "tool": "top-down-planning",
        "contracts": [
            {
                "name": name,
                "version": 1,
                "description": _schema_for(name)["description"],
                "authority": _schema_for(name)["authority"],
                "format": "json-schema",
            }
            for name in PUBLIC_CONTRACTS
        ],
    }


def show_schema(name: str) -> dict[str, Any]:
    return _schema_for(name)


def _example_plan() -> dict[str, Any]:
    plan = PlanState(
        source=SourceMetadata(
            input_file="idea.md",
            output_goal="Produce an actionable implementation plan",
            input_digest=_INPUT_DIGEST,
            output_goal_digest=_OUTPUT_GOAL_DIGEST,
        ),
        plan=[
            PlanItem(
                id="item-001",
                title="Root objective",
                objective="Deliver the requested outcome.",
            )
        ],
    )
    return plan.model_dump(mode="json")


def _example_operation() -> dict[str, Any]:
    return MarkActionableOperation(
        node_id="item-001",
        title="Plan the requested implementation",
        objective="Produce the implementation plan defined by the input and output goal.",
        expected_outputs=["Implementation plan"],
        acceptance_criteria=["Plan is actionable"],
    ).model_dump(mode="json")


def _example_transaction() -> dict[str, Any]:
    return AgentResponse(
        operations=[
            MarkActionableOperation(
                node_id="item-001",
                title="Plan the requested implementation",
                objective=(
                    "Produce the implementation plan defined by the input and output goal."
                ),
            )
        ],
        plan_digest=_PLAN_DIGEST,
        selected_items=["item-001"],
        updates=[],
    ).model_dump(mode="json")


def _example_config() -> dict[str, Any]:
    return {
        "input": "examples/idea.md",
        "output": "planning-output",
        "output_goal": "Produce an actionable implementation plan",
        "generation": {"whole_plan_context": "hybrid"},
        "review": {"enabled": True},
    }


def _example_review_whole_plan() -> dict[str, Any]:
    return WholePlanReviewResult(
        plan_digest=_PLAN_DIGEST,
        decision="approve",
        summary="Plan is complete and consistent.",
    ).model_dump(mode="json")


def _example_review_final_confirmation() -> dict[str, Any]:
    return FinalConfirmationResult(
        plan_digest=_PLAN_DIGEST,
        decision="confirmed",
        summary="Ready to render.",
    ).model_dump(mode="json")


def _example_review_render_batch() -> dict[str, Any]:
    from top_down_planning.models import RenderBatchReviewDecision

    return RenderBatchReviewResult(
        batch_index=0,
        plan_digest=_PLAN_DIGEST,
        output_goal_digest=_OUTPUT_GOAL_DIGEST,
        processed_batches_digest="d" * 64,
        deliverable_output_digest="e" * 64,
        decision=RenderBatchReviewDecision.APPROVE,
        summary="Batch integrated successfully.",
    ).model_dump(mode="json")


def _example_review_rendered_output() -> dict[str, Any]:
    from top_down_planning.models import RenderOutputReviewDecision

    return RenderedOutputReviewResult(
        plan_digest=_PLAN_DIGEST,
        output_goal_digest=_OUTPUT_GOAL_DIGEST,
        processed_batches_digest="d" * 64,
        deliverable_output_digest="e" * 64,
        decision=RenderOutputReviewDecision.APPROVE,
        summary="Rendered output is complete.",
    ).model_dump(mode="json")


def _example_by_name(name: str) -> dict[str, Any]:
    builders = {
        "config": _example_config,
        "plan": _example_plan,
        "operation": _example_operation,
        "transaction": _example_transaction,
        "review-whole-plan": _example_review_whole_plan,
        "review-final-confirmation": _example_review_final_confirmation,
        "review-render-batch": _example_review_render_batch,
        "review-rendered-output": _example_review_rendered_output,
    }
    if name not in builders:
        known = ", ".join(PUBLIC_CONTRACTS)
        raise KeyError(f"Unknown example {name!r}; known: {known}")
    return builders[name]()


def list_examples() -> dict[str, Any]:
    return {"tool": "top-down-planning", "examples": list(PUBLIC_CONTRACTS)}


def show_example(name: str) -> dict[str, Any]:
    return {"name": name, "example": _example_by_name(name)}


def validate_example(name: str, payload: dict[str, Any]) -> None:
    if name == "config":
        _CONFIG_ADAPTER.validate_python(payload)
        return
    if name == "plan":
        _PLAN_ADAPTER.validate_python(payload)
        return
    if name == "operation":
        _OPERATION_ADAPTER.validate_python(payload)
        return
    if name == "transaction":
        _TRANSACTION_ADAPTER.validate_python(payload)
        return
    if name == "review-whole-plan":
        _WHOLE_PLAN_REVIEW_ADAPTER.validate_python(payload)
        return
    if name == "review-final-confirmation":
        _FINAL_CONFIRMATION_ADAPTER.validate_python(payload)
        return
    if name == "review-render-batch":
        _RENDER_BATCH_REVIEW_ADAPTER.validate_python(payload)
        return
    if name == "review-rendered-output":
        _RENDERED_OUTPUT_REVIEW_ADAPTER.validate_python(payload)
        return
    known = ", ".join(PUBLIC_CONTRACTS)
    raise KeyError(f"Unknown contract {name!r}; known: {known}")


def validate_operation(payload: dict[str, Any]) -> None:
    _OPERATION_ADAPTER.validate_python(payload)


def validate_update(payload: dict[str, Any]) -> None:
    _UPDATE_ADAPTER.validate_python(payload)


def validate_review_result(stage: str, payload: dict[str, Any]) -> None:
    adapters: dict[str, TypeAdapter[Any]] = {
        "whole_plan_review": _WHOLE_PLAN_REVIEW_ADAPTER,
        "final_confirmation": _FINAL_CONFIRMATION_ADAPTER,
        "render_batch_review": _RENDER_BATCH_REVIEW_ADAPTER,
        "rendered_output_review": _RENDERED_OUTPUT_REVIEW_ADAPTER,
    }
    if stage not in adapters:
        known = ", ".join(REVIEW_STAGES)
        raise KeyError(f"Unknown review stage {stage!r}; known: {known}")
    adapters[stage].validate_python(payload)


def operation_schema(*, target: Literal["operation", "transaction"] = "operation") -> dict[str, Any]:
    if target == "transaction":
        return _TRANSACTION_ADAPTER.json_schema()
    return _OPERATION_ADAPTER.json_schema()


def operation_examples() -> dict[str, dict[str, Any]]:
    return {
        "mark_actionable": _example_operation(),
        "expand": {
            "type": "expand",
            "node_id": "item-001",
            "reason": "Break down the root objective",
            "title": "Plan the requested migration",
            "objective": "Produce the migration plan defined by the source and output goal.",
            "children": [
                {
                    "ref": "child-1",
                    "title": "First child",
                    "objective": "Deliver the first slice.",
                }
            ],
        },
        "update_item": {
            "type": "update_item",
            "node_id": "item-002",
            "reason": "Align dependency with the newly expanded sibling scope.",
            "dependencies": ["item-003"],
            "notes": ["Depends on the API contract item before implementation."],
        },
    }


def review_schema(stage: str) -> dict[str, Any]:
    adapters: dict[str, TypeAdapter[Any]] = {
        "whole_plan_review": _WHOLE_PLAN_REVIEW_ADAPTER,
        "final_confirmation": _FINAL_CONFIRMATION_ADAPTER,
        "render_batch_review": _RENDER_BATCH_REVIEW_ADAPTER,
        "rendered_output_review": _RENDERED_OUTPUT_REVIEW_ADAPTER,
    }
    if stage not in adapters:
        known = ", ".join(REVIEW_STAGES)
        raise KeyError(f"Unknown review stage {stage!r}; known: {known}")
    return adapters[stage].json_schema()


def review_example(stage: str) -> dict[str, Any]:
    examples = {
        "whole_plan_review": _example_review_whole_plan,
        "final_confirmation": _example_review_final_confirmation,
        "render_batch_review": _example_review_render_batch,
        "rendered_output_review": _example_review_rendered_output,
    }
    if stage not in examples:
        known = ", ".join(REVIEW_STAGES)
        raise KeyError(f"Unknown review stage {stage!r}; known: {known}")
    return examples[stage]()


def format_plan_tool_usage(*, plan_tool_command: str = "planning-plan-tool") -> str:
    return f"""Use the planning transaction CLI — do **not** return JSON in chat and do **not**
edit `.planning-output/plan.yaml` directly.

Authoritative schemas and examples:
  {plan_tool_command} schema --target operation
  {plan_tool_command} schema --target transaction
  {plan_tool_command} example --type mark_actionable
  {plan_tool_command} example --type update_item
  {plan_tool_command} validate --json '<operation>'
  {plan_tool_command} validate-update --json '<update_item>'

Workflow:
1. Read the eligible items, processed-batch history, and complete plan overview.
2. Choose a coherent batch and run `{plan_tool_command} select-batch --node-id <id> [--purpose "..."]`.
3. Optionally run `{plan_tool_command} show-context` for selected-node details.
4. Optionally run `{plan_tool_command} status` to inspect the current draft.
5. For **each selected item**, run `{plan_tool_command} record-operation --json '<operation>'`.
6. Optionally run `{plan_tool_command} record-update --json '<update_item>'` for related items
   listed in the patchable scope. Omitted fields preserve the current value; an empty list
   clears a list field.
7. Run `{plan_tool_command} finalize` to commit the session transaction."""


def format_amend_tool_usage(*, plan_tool_command: str = "planning-plan-tool") -> str:
    return f"""Use the planning transaction CLI — do **not** return JSON in chat and do **not**
edit `.planning-output/plan.yaml` directly.

Authoritative schemas and examples:
  {plan_tool_command} schema --target operation
  {plan_tool_command} schema --target transaction
  {plan_tool_command} example --type mark_actionable
  {plan_tool_command} validate --json '<operation>'

Workflow:
1. Review eligible items, processed batches, and review findings below.
2. Record your batch with `{plan_tool_command} select-batch --node-id <id> [--purpose "..."]`.
3. For **each selected item**, run `{plan_tool_command} record-operation --json '<revise_actionable>'`.
4. Run `{plan_tool_command} finalize` to commit the session transaction.

Amend sessions use `revise_actionable` only. Do not use `record-update`."""


def format_review_schema_section(
    *,
    review_tool_command: str,
    stage: str,
    plan_digest: str,
) -> str:
    return f"""## Structured result schema
Use `{review_tool_command} set-result --json '<json>'` then `{review_tool_command} finalize`.

Authoritative schema and example:
  {review_tool_command} schema --stage {stage}
  {review_tool_command} example --stage {stage}
  {review_tool_command} validate --json '<json>' --stage {stage}

Required `plan_digest` for this session: `{plan_digest}`"""


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
                f"  {contract['name']:<28} v{contract['version']}  {contract['description']}"
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
