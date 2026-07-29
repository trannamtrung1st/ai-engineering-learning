"""Prompt builders for whole-plan review and final confirmation."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.agent_context import ResolvedAgentContext
from top_down_planning.completeness import structural_errors
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.models import PlanState
from top_down_planning.prompts import (
    _format_agent_context_section,
    format_input_document_section,
    format_output_goal_section,
    format_stop_hint_section,
)
from top_down_planning.render_brief import build_render_brief
from top_down_planning.review_tool import resolve_review_tool_command
from top_down_planning import schema_docs


def _dependency_summary(plan: PlanState) -> str:
    lines: list[str] = []
    for item in sorted(plan.plan, key=lambda entry: (entry.order, entry.id)):
        if not item.dependencies:
            continue
        deps = ", ".join(item.dependencies)
        lines.append(f"- [{item.id}] {item.title}: depends on {deps}")
    if not lines:
        return "No dependencies recorded."
    return "\n".join(lines)


def _plan_hierarchy(plan: PlanState) -> str:
    lines: list[str] = []

    def walk(parent_id: str | None, indent: int) -> None:
        for child in plan.children_of(parent_id):
            prefix = "  " * indent
            lines.append(
                f"{prefix}- [{child.id}] {child.title} "
                f"({child.decomposition_status.value})"
            )
            walk(child.id, indent + 1)

    walk(None, 0)
    return "\n".join(lines) if lines else "No plan items."


def build_whole_plan_review_prompt(
    *,
    loaded_input: LoadedInput,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    stop_hint: LoadedStopHint | None,
    plan: PlanState,
    plan_digest: str,
    embed_threshold: int,
    review_tool_command: str = "planning-review-tool",
    agent_context: ResolvedAgentContext | None = None,
) -> str:
    stop_hint_block = ""
    if stop_hint is not None:
        stop_hint_block = (
            "## Stop hint\n"
            f"{format_stop_hint_section(stop_hint=stop_hint, workspace=workspace, embed_threshold=embed_threshold)}\n\n"
        )
    validation = structural_errors(plan)
    validation_block = (
        "Deterministic validation passed."
        if not validation
        else "Deterministic validation issues:\n"
        + "\n".join(f"- {error}" for error in validation)
    )
    return f"""# Whole-plan review session

You are a read-only planning reviewer. Evaluate the completed decomposition for
semantic quality. Do not modify `plan.yaml`, do not write deliverables, and do not
redesign the plan creatively.

Record exactly one structured review result through the review transaction CLI.

## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

{stop_hint_block}{_format_agent_context_section(agent_context)}## Plan digest
`{plan_digest}`

## Deterministic validation
{validation_block}

## Dependency summary
{_dependency_summary(plan)}

## Hierarchy
{_plan_hierarchy(plan)}

## Actionable-leaf render brief
{build_render_brief(plan)}

## Primary input
{format_input_document_section(loaded_input=loaded_input, workspace=workspace, embed_threshold=embed_threshold)}

## Evaluation checklist
- Coverage: explicit source requirements represented; required sibling groups distinct;
  nothing important omitted; non-goals not leaked into scope.
- Consistency: no contradictions; no substantial duplicate scope; assumptions aligned.
- Decomposition quality: actionable leaves bounded for the output goal; granularity
  reasonably consistent; render should not require major design rediscovery.
- Dependency quality: real prerequisites only; preferred order not encoded as hard deps.
- Completion quality: concrete expected outputs and observable acceptance criteria where
  the output goal requires them; no contradictory criteria; unresolved decisions surfaced
  via blocked items or open questions when needed.
- Ownership: each major concern has a clear owner; no overlapping duplicate workstreams.
- Scope framing: named examples and paths are investigation anchors unless the source
  explicitly treats them as exhaustive inventories.
- Checkpoint discipline: avoid mechanical checkpoint leaves when one correction leaf can
  own the verification.

{schema_docs.format_review_schema_section(
    review_tool_command=review_tool_command,
    stage="whole_plan_review",
    plan_digest=plan_digest,
)}

Revision modes (required on every finding when decision is `needs_revision`):
- `amend` — actionable item detail is wrong (acceptance criteria, sequencing, wording).
  Cite only the actionable node ids to patch in place. Do not cite ancestors
  together with descendants.
- `reopen` — branch structure or decomposition is wrong. Cite only the minimal reopen
  root id(s). Never cite both a parent and its descendant in the same finding.
- `annotate` — minor note or reminder that should not trigger replanning. Optional
  `node_ids`; the note is attached to cited items when present.

Rules:
- `approve` cannot include blocking or major findings.
- `needs_revision` must include at least one finding with `revision_mode` and, for
  `reopen`/`amend`, affected node ids.
- Prefer `amend` over `reopen` when the decomposition tree is correct but detail on
  actionable leaves needs correction.
- Use `annotate` for minor nits that do not require agent replanning.
- `blocked` must explain the unresolved condition in summary.
- `plan_digest` must match exactly.
- Do not modify files under `.planning-output/` except through `{review_tool_command}`.
"""


def build_final_confirmation_prompt(
    *,
    loaded_input: LoadedInput,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    stop_hint: LoadedStopHint | None,
    plan: PlanState,
    plan_digest: str,
    embed_threshold: int,
    review_tool_command: str = "planning-review-tool",
    agent_context: ResolvedAgentContext | None = None,
) -> str:
    stop_hint_block = ""
    if stop_hint is not None:
        stop_hint_block = (
            "## Stop hint\n"
            f"{format_stop_hint_section(stop_hint=stop_hint, workspace=workspace, embed_threshold=embed_threshold)}\n\n"
        )
    validation = structural_errors(plan)
    validation_block = (
        "Deterministic validation passed."
        if not validation
        else "Deterministic validation issues:\n"
        + "\n".join(f"- {error}" for error in validation)
    )
    return f"""# Final confirmation session

You are a read-only final confirmer. Confirm the plan is ready to render. Do not
modify `plan.yaml`, do not write deliverables, and do not redesign the plan.

Record exactly one structured confirmation result through the review transaction CLI.

## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

{stop_hint_block}{_format_agent_context_section(agent_context)}## Plan digest
`{plan_digest}`

## Deterministic validation
{validation_block}

## Hierarchy
{_plan_hierarchy(plan)}

## Actionable-leaf render brief
{build_render_brief(plan)}

## Primary input
{format_input_document_section(loaded_input=loaded_input, workspace=workspace, embed_threshold=embed_threshold)}

## Confirm
- Digest matches the current plan.
- Deterministic validation is green.
- Explicit source structure is preserved.
- Blocking and major findings are resolved.
- Every actionable leaf is renderable.
- Dependency graph is coherent.
- Output goal can be rendered without major planning rediscovery.
- Named examples and paths are investigation anchors unless the source says otherwise.
- No unnecessary checkpoint-like leaves when one correction leaf can own verification.

{schema_docs.format_review_schema_section(
    review_tool_command=review_tool_command,
    stage="final_confirmation",
    plan_digest=plan_digest,
)}

Rules:
- `confirmed` requires matching digest and no blocking/major findings.
- `confirmed` cannot override failed deterministic validation.
- `needs_revision` or `blocked` must explain why rendering must not proceed.
- When `findings` is non-empty, each entry requires `revision_mode`.
- Do not modify files under `.planning-output/` except through `{review_tool_command}`.
"""
