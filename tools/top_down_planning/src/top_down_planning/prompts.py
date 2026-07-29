"""Construct bounded planning prompts for the agent."""

from __future__ import annotations

import json
from pathlib import Path

from top_down_planning import schema_docs
from top_down_planning.agent_context import ResolvedAgentContext
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.item_format import format_item_context, format_item_summary
from top_down_planning.models import (
    CheckpointFinding,
    PlanItem,
    PlanState,
    PlanningLimits,
    PlanningState,
    ProcessedBatchRecord,
    ReviewCheckpoint,
)


def should_embed_content(text: str, *, embed_threshold: int) -> bool:
    """Return True when content is short enough to inline in the prompt."""
    return len(text.strip()) <= embed_threshold


def format_embedded_markdown(text: str) -> str:
    """Wrap Markdown or text content in a fenced block for prompt embedding."""
    return f"```markdown\n{text.strip()}\n```"


def format_input_file_reference(input_file: Path, workspace: Path) -> str:
    """Return workspace-relative and absolute paths for a file reference."""
    resolved = input_file.resolve()
    try:
        display_path = str(resolved.relative_to(workspace.resolve())).replace("\\", "/")
    except ValueError:
        display_path = str(resolved)
    return (
        f"- Path: `{display_path}`\n"
        f"- Absolute: `{resolved}`"
    )


def _format_agent_context_section(resolved: ResolvedAgentContext | None) -> str:
    if resolved is None or (not resolved.skills and not resolved.rules):
        return ""
    parts: list[str] = ["## Agent context"]
    if resolved.skills:
        skill_lines = "\n".join(f"- `{path}`" for path in resolved.skills)
        parts.extend(
            [
                "",
                "### Applicable skills",
                skill_lines,
                "",
                "Read each listed skill file before acting and follow its guidance.",
            ]
        )
    if resolved.rules:
        rule_lines = "\n".join(f"- `{path}`" for path in resolved.rules)
        parts.extend(
            [
                "",
                "### Applicable rules",
                rule_lines,
                "",
                "Read each listed rule file before acting and apply its constraints.",
            ]
        )
    return "\n".join(parts) + "\n\n"


def format_output_goal_section(
    *,
    output_goal: LoadedOutputGoal,
    workspace: Path,
    embed_threshold: int,
) -> str:
    text = output_goal.text.strip()
    if should_embed_content(text, embed_threshold=embed_threshold):
        return format_embedded_markdown(text)
    if output_goal.path is not None:
        return (
            "Read the output goal specification before planning:\n\n"
            f"{format_input_file_reference(output_goal.path, workspace)}\n\n"
            "Open and read that file in full. It defines the desired final plan "
            "shape, actionability criteria, and rendering expectations."
        )
    return format_embedded_markdown(text)


def format_stop_hint_section(
    *,
    stop_hint: LoadedStopHint,
    workspace: Path,
    embed_threshold: int,
) -> str:
    text = stop_hint.text.strip()
    if should_embed_content(text, embed_threshold=embed_threshold):
        return format_embedded_markdown(text)
    if stop_hint.path is not None:
        return (
            "Read the expansion stop guidance before deciding whether to expand or stop:\n\n"
            f"{format_input_file_reference(stop_hint.path, workspace)}\n\n"
            "Open and read that file in full. Use it when choosing `expand` "
            "or `mark_actionable`."
        )
    return format_embedded_markdown(text)


def format_input_document_section(
    *,
    loaded_input: LoadedInput,
    workspace: Path,
    embed_threshold: int,
) -> str:
    text = loaded_input.text.strip()
    if should_embed_content(text, embed_threshold=embed_threshold):
        return (
            "The complete primary input Markdown document:\n\n"
            f"{format_embedded_markdown(text)}"
        )
    return (
        "Read the complete primary input Markdown file before planning:\n\n"
        f"{format_input_file_reference(loaded_input.path, workspace)}\n\n"
        "Open and read that file in full. Treat its entire contents as the "
        "source planning context."
    )


def remaining_depth_budget(item: PlanItem, *, max_depth: int) -> int:
    """Levels below this item that may still be created (0 means must not expand)."""
    return max(0, max_depth - item.depth)


def format_eligible_items_section(items: list[PlanItem]) -> str:
    if not items:
        return "No eligible items remain for this session."
    lines = ["| id | depth | title | status |", "| --- | --- | --- | --- |"]
    for item in items:
        lines.append(
            f"| {item.id} | {item.depth} | {item.title} | "
            f"{item.decomposition_status.value} |"
        )
    return "\n".join(lines)


def format_planning_eligible_items_section(
    items: list[PlanItem],
    *,
    limits: PlanningLimits,
) -> str:
    if not items:
        return "No eligible items remain for this session."
    lines = [
        "| id | depth | remaining_depth | max_children | title | status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        remaining = remaining_depth_budget(item, max_depth=limits.max_depth)
        lines.append(
            f"| {item.id} | {item.depth} | {remaining} | "
            f"{limits.max_children_per_expansion} | {item.title} | "
            f"{item.decomposition_status.value} |"
        )
    return "\n".join(lines)


def format_expansion_limits_section(*, limits: PlanningLimits) -> str:
    return (
        "## Expansion limits\n"
        f"- `max_depth`: {limits.max_depth} (root depth is 0).\n"
        f"- `max_children_per_expansion`: {limits.max_children_per_expansion} "
        "(maximum direct children per `expand`).\n"
        "- Plan within these limits before recording operations. The eligible-items "
        "table shows each item's `remaining_depth` and per-expand child cap.\n"
        "- When `remaining_depth` is 0, use `mark_actionable` instead of `expand`.\n"
        "- When an item has more detail than fits in the child cap, group related "
        "concerns into fewer children and capture ancillary detail in `notes`, "
        "`expected_outputs`, `acceptance_criteria`, `risks`, or `open_questions`.\n"
        "- Do not use `mark_blocked` solely because a structural limit was reached.\n"
        "- Expand only for independently trackable planning concerns; do not create "
        "child items for every bullet or minor detail in the source.\n\n"
    )


def format_processed_batches_section(records: list[ProcessedBatchRecord]) -> str:
    if not records:
        return "No prior batches have been processed in this run."
    lines: list[str] = []
    for record in records[-12:]:
        items = ", ".join(record.selected_items)
        purpose = f" — {record.purpose}" if record.purpose.strip() else ""
        lines.append(
            f"- Iteration {record.iteration}: [{items}]{purpose} "
            f"(result={record.result})"
        )
    if len(records) > 12:
        lines.insert(0, f"(Showing last 12 of {len(records)} processed batches.)")
    lines.append(
        "Processed batches are history for context. You may revisit any batch for "
        "refinement when the current plan state warrants it."
    )
    return "\n".join(lines)


def build_planning_prompt(
    *,
    loaded_input: LoadedInput,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan: PlanState,
    eligible_items: list[PlanItem],
    processed_batches: list[ProcessedBatchRecord],
    embed_threshold: int,
    limits: PlanningLimits,
    stop_hint: LoadedStopHint | None = None,
    validation_feedback: list[str] | None = None,
    plan_tool_command: str = "planning-plan-tool",
    agent_context: ResolvedAgentContext | None = None,
    plan_digest: str,
    batch_context_markdown: str,
) -> str:
    stop_hint_block = ""
    if stop_hint is not None:
        stop_hint_block = (
            "## Expansion stop guidance\n"
            "Use this when deciding whether to `expand` or `mark_actionable`:\n\n"
            f"{format_stop_hint_section(stop_hint=stop_hint, workspace=workspace, embed_threshold=embed_threshold)}\n\n"
        )

    generation_context_block = (
        f"## Generation context\n\n"
        f"Plan digest: `{plan_digest}`\n\n"
        f"{batch_context_markdown}\n\n"
    )

    eligible_block = (
        "## Eligible items\n"
        "Choose a coherent batch from these items. Prefer same-parent siblings or "
        "nearby depth when batching multiple items.\n\n"
        f"{format_planning_eligible_items_section(eligible_items, limits=limits)}\n\n"
    )

    history_block = (
        "## Processed batches\n"
        f"{format_processed_batches_section(processed_batches)}\n\n"
    )

    feedback_block = ""
    if validation_feedback:
        feedback_block = (
            "## Validation feedback from previous attempt\n"
            + "\n".join(f"- {error}" for error in validation_feedback)
            + "\n\nFix every issue and finalize a valid transaction.\n\n"
        )

    return f"""# Top-down planning session

You are a planning agent. Analyze the assigned planning items and record structured
operations through the planning transaction CLI. Do not rewrite the full plan state.
Do not execute implementation work.

## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

{stop_hint_block}{_format_agent_context_section(agent_context)}{format_expansion_limits_section(limits=limits)}## Workflow
1. Review the eligible items and processed-batch history.
2. Choose a coherent batch and record it with `{plan_tool_command} select-batch`.
3. Optionally run `{plan_tool_command} show-context` for selected-node details.
4. Record one operation per selected item, then finalize the transaction.

## Rules
- Choose batch scope based on the output goal, stop guidance, and remaining work.
- You may revisit items from prior processed batches when refinement is needed.
- Record exactly one operation per **selected** item only.
- When your assigned decomposition changes related items, record `update_item` patches
  immediately for items listed in the patchable scope.
- For cross-item updates, omitted fields preserve the current value and an empty list
  clears a list field.
- For the root item's operation, provide `title` and `objective` that specifically
  summarize the input and requested output; do not preserve its generic bootstrap wording.
- You may optionally refine the assigned item's `title` and/or `objective` when the
  current wording is misleading or too narrow for the output goal.
- Use `expand` when the item still contains multiple meaningful planning concerns
  and `remaining_depth` is greater than 0.
  Expanding marks the parent `expanded` and creates child items for further decomposition.
- Use `mark_actionable` when the item is a leaf detailed enough for the output goal,
  or when `remaining_depth` is 0.
- When finer source detail does not warrant its own child, keep it on the actionable
  item in `notes`, `expected_outputs`, `acceptance_criteria`, `risks`, or
  `open_questions` instead of expanding further.
- Use `mark_blocked` only when required information is missing and cannot be inferred safely.
- Use `mark_out_of_scope` when the item does not contribute to the output goal.
- Do not invent canonical item IDs. The orchestrator assigns IDs on apply.
- For sibling dependencies in an `expand`, use child `ref` values or existing item ids.
Prefer breadth-first planning: the orchestrator only exposes the shallowest
incomplete depth as eligible items, so keep major areas coherent before over-detailing
one branch.
- Do not write final deliverable files during this session. A dedicated render phase runs
  after decomposition completes.
- Do not modify files under `.planning-output/` except through `{plan_tool_command}`.

## Planning quality checks
- Preserve explicit requirements from the input document and output goal.
- Avoid unnecessary repeated decomposition or checkpoint-like leaves when one leaf can
  own the work.
- Use dependencies only for real prerequisites, not preferred execution order.
- Treat named examples, paths, and concerns as investigation anchors unless the source
  explicitly treats them as exhaustive scope.

{feedback_block}{eligible_block}{history_block}## Input document

{format_input_document_section(loaded_input=loaded_input, workspace=workspace, embed_threshold=embed_threshold)}

{generation_context_block}## Planning transaction CLI
{schema_docs.format_plan_tool_usage(plan_tool_command=plan_tool_command)}
"""


def format_planning_state_section(planning_state: PlanningState) -> str:
    import yaml

    payload = planning_state.model_dump(mode="json", exclude={"updated_at"})
    return (
        "## Serialized planning state\n"
        "Treat this as durable authority alongside the plan. Update it every iteration.\n\n"
        f"```yaml\n{yaml.safe_dump(payload, sort_keys=False)}```\n"
    )


def build_continuation_prompt(
    *,
    loaded_input: LoadedInput,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan: PlanState,
    planning_state: PlanningState,
    eligible_items: list[PlanItem],
    processed_batches: list[ProcessedBatchRecord],
    embed_threshold: int,
    limits: PlanningLimits,
    stop_hint: LoadedStopHint | None = None,
    validation_feedback: list[str] | None = None,
    plan_tool_command: str = "planning-plan-tool",
    agent_context: ResolvedAgentContext | None = None,
    plan_digest: str,
    batch_context_markdown: str,
    selected_branch_summary: str,
) -> str:
    base = build_planning_prompt(
        loaded_input=loaded_input,
        workspace=workspace,
        output_goal=output_goal,
        plan=plan,
        eligible_items=eligible_items,
        processed_batches=processed_batches,
        embed_threshold=embed_threshold,
        limits=limits,
        stop_hint=stop_hint,
        validation_feedback=validation_feedback,
        plan_tool_command=plan_tool_command,
        agent_context=agent_context,
        plan_digest=plan_digest,
        batch_context_markdown=batch_context_markdown,
    )
    continuation = f"""
## Primary planner continuation

Refine the selected branch against the current complete plan. Before modifying it, check its
responsibility boundary, sibling overlap, dependencies, output-goal coverage, and stopping
condition. Update the global plan and serialized planning state. Do not reopen frozen decisions
without concrete contradictory evidence.

### Selected work
{selected_branch_summary}

{format_planning_state_section(planning_state)}

After recording plan operations, record a planning-state update with
`{plan_tool_command} record-planning-state-update --json '<update>'`.
"""
    return base.replace(
        "# Top-down planning session",
        "# Top-down planning continuation session",
        1,
    ) + continuation


def build_disposition_prompt(
    *,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    planning_state: PlanningState,
    findings: list[CheckpointFinding],
    checkpoint: ReviewCheckpoint,
    plan_digest: str,
    embed_threshold: int,
    disposition_context_markdown: str = "",
    plan_tool_command: str = "planning-plan-tool",
    agent_context: ResolvedAgentContext | None = None,
    validation_feedback: list[str] | None = None,
) -> str:
    finding_lines: list[str] = []
    for finding in findings:
        finding_lines.append(
            f"- `{finding.id}` ({finding.severity.value}/{finding.category.value}): "
            f"{finding.observation}"
        )
        if finding.affected_branches:
            branches = ", ".join(finding.affected_branches)
            finding_lines.append(f"  - Affected branches: {branches}")
        if finding.recommended_disposition:
            finding_lines.append(
                f"  - Recommended disposition: {finding.recommended_disposition}"
            )
    findings_block = "\n".join(finding_lines) or "- No findings supplied."
    feedback_block = _format_validation_feedback(validation_feedback)
    context_block = ""
    if disposition_context_markdown.strip():
        context_block = f"## Plan context\n\n{disposition_context_markdown.rstrip()}\n\n"
    return f"""# Finding disposition session

You are the primary planner. Classify every reviewer finding and update plan/state for accepted
items. Do not ignore findings silently.

## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

{_format_agent_context_section(agent_context)}{feedback_block}## Checkpoint
`{checkpoint.value}`

## Plan digest
`{plan_digest}`

{format_planning_state_section(planning_state)}

{context_block}## Reviewer findings
{findings_block}

## Patch rules for `record-update`
- Disposition sessions patch existing items only; do not use `select-batch` or
  `record-operation`.
- For items with `decomposition_status` other than `actionable`, you may change only:
  `title`, `objective`, `notes`, `dependencies`, `risks`, and `open_questions`.
- `expected_outputs` and `acceptance_criteria` may be changed only on `actionable`
  items. For `needs_expansion` or `expanded` items, capture boundary and routing
  detail in `title`, `objective`, and `notes` instead; refine outputs and criteria
  when the branch is marked actionable.
- Every update requires a non-empty `reason`.
- Omitted fields preserve the current value; an empty list clears a list field.
- Use `{plan_tool_command} validate-update --json '<update_item>'` to check an update
  against the current plan before finalize.

## Required dispositions
For every finding, choose one of:
`accepted`, `partially_accepted`, `rejected`, `already_covered`, `deferred`, `not_applicable`.

Record dispositions and any resulting plan/state changes:
1. Use `{plan_tool_command} record-planning-state-update --json '<update>'` with
   `finding_dispositions` and any plan-impacting state fields.
2. If plan graph changes are required, use `{plan_tool_command} record-update --json
   '<update_item>'` for each affected item.
3. Run `{plan_tool_command} finalize`.

Accepted findings must produce concrete plan or state changes with concise rationale.

{schema_docs.format_disposition_tool_usage(plan_tool_command=plan_tool_command)}
"""


def _render_author_instructions() -> str:
    return """Write deliverables directly to workspace destination paths.

- Read the current workspace deliverables listed in context before editing.
- Integrate your contribution into the existing output without discarding valid prior work.
- You may use temporary files internally, but final content must live at workspace paths.
- Do not modify files under `.planning-output/`.
"""


def build_render_scaffold_prompt(
    *,
    plan_digest: str,
    output_goal_digest: str,
    render_config_digest: str,
    context_markdown: str,
    output_goal: LoadedOutputGoal,
    workspace: Path,
    embed_threshold: int,
    validation_feedback: list[str] | None = None,
    agent_context: ResolvedAgentContext | None = None,
) -> str:
    feedback_block = _format_validation_feedback(validation_feedback)
    return f"""# Render scaffold session

Establish destination paths, overall structure, and formatting conventions for the deliverables.

## Plan digest
`{plan_digest}`

## Output-goal digest
`{output_goal_digest}`

## Render-config digest
`{render_config_digest}`

{feedback_block}{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## Context
{context_markdown}

{_render_author_instructions()}
## Instructions
- Create the initial scaffold files at workspace paths implied by the output goal.
- Leave clear section placeholders for later batch authors to fill in.
- Do not modify canonical planning files.
"""


def build_render_batch_author_prompt(
    *,
    batch_index: int,
    plan_digest: str,
    output_goal_digest: str,
    render_config_digest: str,
    context_markdown: str,
    output_goal: LoadedOutputGoal,
    workspace: Path,
    embed_threshold: int,
    validation_feedback: list[str] | None = None,
    agent_context: ResolvedAgentContext | None = None,
) -> str:
    feedback_block = _format_validation_feedback(validation_feedback)
    return f"""# Render batch author session: batch {batch_index}

Integrate the assigned plan items into the cumulative workspace deliverables.

## Plan digest
`{plan_digest}`

## Output-goal digest
`{output_goal_digest}`

## Render-config digest
`{render_config_digest}`

{feedback_block}{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## Context
{context_markdown}

{_render_author_instructions()}
## Instructions
- Cover every assigned plan item in the current workspace deliverables.
- Preserve expected outputs, acceptance criteria, notes, risks, and scope boundaries
  recorded on assigned plan items.
- Preserve valid content from earlier batches and the scaffold.
- Do not modify canonical planning files.
"""


def build_render_batch_revision_prompt(
    *,
    batch_index: int,
    plan_digest: str,
    output_goal_digest: str,
    render_config_digest: str,
    context_markdown: str,
    output_goal: LoadedOutputGoal,
    workspace: Path,
    embed_threshold: int,
    findings_summary: str,
    validation_feedback: list[str] | None = None,
    agent_context: ResolvedAgentContext | None = None,
) -> str:
    feedback_block = _format_validation_feedback(validation_feedback)
    return f"""# Render batch revision session: batch {batch_index}

Revise the cumulative workspace deliverables to address batch review findings.

## Plan digest
`{plan_digest}`

## Output-goal digest
`{output_goal_digest}`

## Render-config digest
`{render_config_digest}`

{feedback_block}{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## Review findings
{findings_summary or "_No findings provided._"}

## Context
{context_markdown}

{_render_author_instructions()}
## Instructions
- Address every review finding for this batch.
- Edit workspace deliverables directly; do not modify canonical planning files.
"""


def build_render_final_revision_prompt(
    *,
    plan_digest: str,
    output_goal_digest: str,
    render_config_digest: str,
    context_markdown: str,
    output_goal: LoadedOutputGoal,
    workspace: Path,
    embed_threshold: int,
    findings_summary: str,
    validation_feedback: list[str] | None = None,
    agent_context: ResolvedAgentContext | None = None,
) -> str:
    feedback_block = _format_validation_feedback(validation_feedback)
    return f"""# Render final revision session

Revise the complete workspace deliverables to address final output review findings.

## Plan digest
`{plan_digest}`

## Output-goal digest
`{output_goal_digest}`

## Render-config digest
`{render_config_digest}`

{feedback_block}{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## Review findings
{findings_summary or "_No findings provided._"}

## Context
{context_markdown}

{_render_author_instructions()}
## Instructions
- Address every final review finding.
- Edit workspace deliverables directly; do not modify canonical planning files.
"""


def build_render_batch_review_prompt(
    *,
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan_digest: str,
    processed_batches_digest: str,
    batch_index: int,
    batch_item_ids: list[str],
    deliverable_digest: str,
    deliverable_paths: list[str],
    output_goal_digest: str,
    embed_threshold: int,
    agent_context: ResolvedAgentContext | None = None,
    review_tool_command: str = "planning-review-tool",
) -> str:
    from top_down_planning.persistence import plan_path, render_state_path

    plan_file = plan_path(output_dir)
    render_state_file = render_state_path(output_dir)
    destination_lines = "\n".join(
        f"- {format_input_file_reference(workspace / relative_path, workspace)}"
        for relative_path in deliverable_paths
    ) or "- _No workspace deliverables were created yet._"

    return f"""# Render batch review session: batch {batch_index}

Review the cumulative workspace deliverables after batch {batch_index} authoring.

Assigned plan items: {", ".join(batch_item_ids)}

## Plan digest
`{plan_digest}`

## Output-goal digest
`{output_goal_digest}`

## Processed batches digest
`{processed_batches_digest}`

## Deliverable output digest
`{deliverable_digest}`

{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## References
- Confirmed plan: {format_input_file_reference(plan_file, workspace)}
- Render state: {format_input_file_reference(render_state_file, workspace)}

## Workspace deliverables
{destination_lines}

## Review checklist
- Every assigned plan item appears in the cumulative deliverables with preserved detail.
- Expected outputs, acceptance criteria, notes, risks, and scope boundaries from the plan
  are reflected where relevant.
- No duplicate or contradictory coverage introduced in this batch.

{schema_docs.format_review_schema_section(
    review_tool_command=review_tool_command,
    stage="render_batch_review",
    plan_digest=plan_digest,
)}
"""


def _format_validation_feedback(validation_feedback: list[str] | None) -> str:
    if not validation_feedback:
        return ""
    return (
        "## Validation feedback from previous attempt\n"
        + "\n".join(f"- {error}" for error in validation_feedback)
        + "\n\nFix every issue before ending the session.\n\n"
    )


def build_render_output_review_prompt(
    *,
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan_digest: str,
    processed_batches_digest: str,
    deliverable_digest: str,
    deliverable_paths: list[str],
    output_goal_digest: str,
    embed_threshold: int,
    agent_context: ResolvedAgentContext | None = None,
    review_tool_command: str = "planning-review-tool",
) -> str:
    from top_down_planning.persistence import plan_path, render_state_path

    plan_file = plan_path(output_dir)
    render_state_file = render_state_path(output_dir)
    destination_lines = "\n".join(
        f"- {format_input_file_reference(workspace / relative_path, workspace)}"
        for relative_path in deliverable_paths
    ) or "- _No workspace deliverables were declared._"

    return f"""# Rendered output review session

Compare the confirmed plan, processed render batches, workspace deliverables, and output goal.

Final deliverables live at their **workspace destination paths**.

Use `needs_revision` when targeted revision can fix deliverables.
Use `blocked` for unfixable tool/goal mismatches.

## Plan digest
`{plan_digest}`

## Output-goal digest
`{output_goal_digest}`

## Processed batches digest
`{processed_batches_digest}`

## Deliverable output digest
`{deliverable_digest}`

{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## References
- Confirmed plan: {format_input_file_reference(plan_file, workspace)}
- Render state: {format_input_file_reference(render_state_file, workspace)}

## Workspace deliverables
{destination_lines}

## Review checklist
- Every actionable leaf from the confirmed plan appears in the deliverables.
- Plan detail (outputs, criteria, notes, risks, boundaries) is preserved where relevant.
- No major omissions, contradictions, or unresolved blocking issues remain.

{schema_docs.format_review_schema_section(
    review_tool_command=review_tool_command,
    stage="rendered_output_review",
    plan_digest=plan_digest,
)}
"""
