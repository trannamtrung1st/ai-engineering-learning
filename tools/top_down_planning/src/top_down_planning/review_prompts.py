"""Prompt builders for checkpoint specialist reviews."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.agent_context import ResolvedAgentContext
from top_down_planning.completeness import structural_errors
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.models import PlanState, ReviewCheckpoint, ReviewerRole
from top_down_planning.prompts import (
    _format_agent_context_section,
    format_input_document_section,
    format_output_goal_section,
    format_stop_hint_section,
)
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


_ROLE_TITLES = {
    ReviewerRole.COVERAGE_BOUNDARY: "Coverage and boundary reviewer",
    ReviewerRole.DEPENDENCY_SEQUENCING: "Dependency and sequencing reviewer",
    ReviewerRole.EXECUTABILITY_EVIDENCE: "Executability and evidence reviewer",
    ReviewerRole.ADVERSARIAL: "Final adversarial reviewer",
}


_ROLE_CHECKLISTS = {
    ReviewerRole.COVERAGE_BOUNDARY: (
        "- Every output-goal requirement is covered.\n"
        "- No requirement is covered only implicitly.\n"
        "- Branches do not overlap.\n"
        "- Responsibilities have clear owners.\n"
        "- Exclusions do not create coverage gaps."
    ),
    ReviewerRole.DEPENDENCY_SEQUENCING: (
        "- Dependencies represent real execution constraints.\n"
        "- Document order is not mistaken for dependency order.\n"
        "- No dependency cycles exist.\n"
        "- Parallelizable work is not unnecessarily serialized."
    ),
    ReviewerRole.EXECUTABILITY_EVIDENCE: (
        "- Each actionable leaf can be assigned independently.\n"
        "- Surfaces are sufficiently bounded.\n"
        "- Completion criteria are observable.\n"
        "- Evidence commands prove the stated invariant when present."
    ),
    ReviewerRole.ADVERSARIAL: (
        "- Hidden assumptions and omitted consistency surfaces.\n"
        "- Weak handoffs and unresolved ambiguity.\n"
        "- Branches that will expand unpredictably during implementation.\n"
        "- Completion gates that can pass while the output goal remains unsatisfied."
    ),
}


def build_specialist_review_prompt(
    *,
    loaded_input: LoadedInput,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    stop_hint: LoadedStopHint | None,
    plan: PlanState,
    plan_digest: str,
    embed_threshold: int,
    reviewer_role: ReviewerRole,
    checkpoint: ReviewCheckpoint,
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
    title = _ROLE_TITLES.get(reviewer_role, reviewer_role.value)
    checklist = _ROLE_CHECKLISTS.get(reviewer_role, "- Review the complete plan.")
    return f"""# Specialist review session: {title}

You are an independent read-only reviewer at checkpoint `{checkpoint.value}`.
Report findings only; do not rewrite the plan.

## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

{stop_hint_block}{_format_agent_context_section(agent_context)}## Plan digest
`{plan_digest}`

## Deterministic validation
{validation_block}

## Hierarchy
{_plan_hierarchy(plan)}

## Dependency summary
{_dependency_summary(plan)}

## Primary input
{format_input_document_section(loaded_input=loaded_input, workspace=workspace, embed_threshold=embed_threshold)}

## Review checklist
{checklist}

Record exactly one structured specialist review result through the review transaction CLI.
Each finding must include: `id`, `severity`, `category`, `reviewer_role`, `affected_branches`,
`observation`, `violated_invariant`, `recommended_disposition`, and `evidence`.

{schema_docs.format_review_schema_section(
    review_tool_command=review_tool_command,
    stage="specialist_review",
    plan_digest=plan_digest,
)}

Rules:
- `approve` cannot include blocking findings.
- `needs_revision` must include at least one finding when issues exist.
- `plan_digest` must match exactly.
- Do not modify files under `.planning-output/` except through `{review_tool_command}`.
"""
