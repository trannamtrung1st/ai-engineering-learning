"""Construct bounded planning prompts for the agent."""

from __future__ import annotations

import json
from pathlib import Path

from top_down_planning import schema_docs
from top_down_planning.agent_context import ResolvedAgentContext
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.models import PlanItem, PlanState, ReviewFinding, WholePlanContextMode


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
            "Open and read that file in full. Use it when choosing `expand`, "
            "`mark_actionable`, and `plan_complete` via `set-assessment`."
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


def _ancestors(plan: PlanState, item: PlanItem) -> list[PlanItem]:
    chain: list[PlanItem] = []
    current = item.parent_id
    while current is not None:
        parent = plan.item_by_id(current)
        if parent is None:
            break
        chain.append(parent)
        current = parent.parent_id
    chain.reverse()
    return chain


def _siblings(plan: PlanState, item: PlanItem) -> list[PlanItem]:
    return [
        sibling
        for sibling in plan.children_of(item.parent_id)
        if sibling.id != item.id
    ]


def _format_item_context(plan: PlanState, item: PlanItem) -> str:
    parts = [
        f"### Selected item `{item.id}`",
        f"- Title: {item.title}",
        f"- Objective: {item.objective}",
        f"- Depth: {item.depth}",
        f"- Status: {item.decomposition_status.value}",
    ]
    if item.dependencies:
        parts.append(f"- Dependencies: {', '.join(item.dependencies)}")
    if item.expected_outputs:
        parts.append("- Expected outputs:")
        parts.extend(f"  - {value}" for value in item.expected_outputs)
    if item.acceptance_criteria:
        parts.append("- Acceptance criteria:")
        parts.extend(f"  - {value}" for value in item.acceptance_criteria)
    if item.open_questions:
        parts.append("- Open questions:")
        parts.extend(f"  - {value}" for value in item.open_questions)

    ancestors = _ancestors(plan, item)
    if ancestors:
        parts.append("- Ancestors:")
        for ancestor in ancestors:
            parts.append(f"  - [{ancestor.id}] {ancestor.title}")

    siblings = _siblings(plan, item)
    if siblings:
        parts.append("- Direct siblings:")
        for sibling in siblings:
            parts.append(
                f"  - [{sibling.id}] {sibling.title} "
                f"({sibling.decomposition_status.value})"
            )
    return "\n".join(parts)


def build_planning_prompt(
    *,
    loaded_input: LoadedInput,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan: PlanState,
    selected_items: list[PlanItem],
    embed_threshold: int,
    max_children_per_expansion: int = 12,
    stop_hint: LoadedStopHint | None = None,
    validation_feedback: list[str] | None = None,
    plan_tool_command: str = "planning-plan-tool",
    agent_context: ResolvedAgentContext | None = None,
    plan_digest: str,
    batch_context_markdown: str,
    context_mode: WholePlanContextMode,
) -> str:
    stop_hint_block = ""
    if stop_hint is not None:
        stop_hint_block = (
            "## Expansion stop guidance\n"
            "Use this when deciding whether to `expand`, `mark_actionable`, or set "
            "`plan_complete` with `set-assessment`:\n\n"
            f"{format_stop_hint_section(stop_hint=stop_hint, workspace=workspace, embed_threshold=embed_threshold)}\n\n"
        )

    generation_context_block = (
        f"## Generation context ({context_mode.value})\n\n"
        f"Wave plan digest: `{plan_digest}`\n\n"
        f"{batch_context_markdown}\n\n"
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

{stop_hint_block}{_format_agent_context_section(agent_context)}## Expansion limits
- `max_children_per_expansion`: {max_children_per_expansion} (per expand operation).
- Do not merge, omit, or materially rename explicitly required sibling groups solely to
  satisfy this limit.
- When the required direct-child count exceeds the configured limit, do not distort the
  requested structure. Use `mark_blocked` with `constraint_code: "max_children_exceeded"`
  and `required_min_children` set to the minimum required count. Explain the minimum
  required limit in `reason`.

## Rules
- Choose exactly one operation per **assigned** item only.
- Do not record operations for unassigned nodes.
- For the root item's operation, provide `title` and `objective` that specifically
  summarize the input and requested output; do not preserve its generic bootstrap wording.
- Do not provide operation-level `title` or `objective` for non-root items.
- Use `expand` when the item still contains multiple meaningful planning concerns.
- Use `mark_actionable` when the item is detailed enough for the output goal.
- Use `mark_blocked` only when required information is missing and cannot be inferred safely.
- Use `mark_out_of_scope` when the item does not contribute to the output goal.
- Set `plan_complete` to true only when every relevant item is sufficiently detailed for the
  output goal and no further expansion is warranted.
- Do not invent canonical item IDs. The orchestrator assigns IDs on apply.
- For sibling dependencies in an `expand`, use child `ref` values or existing item ids.
- Prefer breadth-first planning: keep major areas coherent before over-detailing one branch.
- Do not write final deliverable files during this session. A dedicated render phase runs
  after decomposition completes.
- Do not modify files under `.planning-output/` except through `{plan_tool_command}`.

{feedback_block}## Input document

{format_input_document_section(loaded_input=loaded_input, workspace=workspace, embed_threshold=embed_threshold)}

{generation_context_block}## Planning transaction CLI
{schema_docs.format_plan_tool_usage(plan_tool_command=plan_tool_command)}
"""


def _format_review_findings_for_items(
    findings: list[ReviewFinding],
    selected_ids: list[str],
) -> str:
    selected = set(selected_ids)
    lines: list[str] = []
    for index, finding in enumerate(findings, start=1):
        relevant = [node_id for node_id in finding.node_ids if node_id in selected]
        if finding.node_ids and not relevant:
            continue
        target = ", ".join(relevant) if relevant else "(informational)"
        lines.append(f"### Finding {index} — {target}")
        lines.append(f"- Severity: {finding.severity.value}")
        lines.append(f"- Category: {finding.category.value}")
        lines.append(f"- Revision mode: {finding.revision_mode.value}")
        lines.append(f"- Issue: {finding.description}")
        if finding.recommended_change.strip():
            lines.append(f"- Recommended change: {finding.recommended_change}")
    if not lines:
        return "No item-specific review findings were supplied for this batch."
    return "\n".join(lines)


def build_amend_prompt(
    *,
    loaded_input: LoadedInput,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan: PlanState,
    selected_items: list[PlanItem],
    review_findings: list[ReviewFinding],
    embed_threshold: int,
    validation_feedback: list[str] | None = None,
    plan_tool_command: str = "planning-plan-tool",
    agent_context: ResolvedAgentContext | None = None,
    plan_digest: str,
    batch_context_markdown: str,
    context_mode: WholePlanContextMode,
) -> str:
    selected_ids = [item.id for item in selected_items]
    feedback_block = ""
    if validation_feedback:
        feedback_block = (
            "## Validation feedback from previous attempt\n"
            + "\n".join(f"- {error}" for error in validation_feedback)
            + "\n\nFix every issue and finalize a valid transaction.\n\n"
        )

    generation_context_block = (
        f"## Generation context ({context_mode.value})\n\n"
        f"Wave plan digest: `{plan_digest}`\n\n"
        f"{batch_context_markdown}\n\n"
    )

    return f"""# Plan amendment session

You are revising actionable plan items in place after whole-plan review. Apply the
review findings surgically. Do not re-expand branches, do not add or remove plan
items, and do not execute implementation work.

## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

{_format_agent_context_section(agent_context)}## Rules
- Record exactly one `revise_actionable` operation per assigned item.
- Provide full replacement `expected_outputs` and `acceptance_criteria` lists.
- Preserve unaffected detail unless the review finding requires a change.
- Do not record `expand`, `mark_actionable`, `mark_blocked`, or `mark_out_of_scope`.
- Set `plan_complete` to true with `set-assessment` once every assigned item is revised.
- Do not modify files under `.planning-output/` except through `{plan_tool_command}`.

{feedback_block}## Review findings for assigned items
{_format_review_findings_for_items(review_findings, selected_ids)}

## Input document

{format_input_document_section(loaded_input=loaded_input, workspace=workspace, embed_threshold=embed_threshold)}

{generation_context_block}## Planning transaction CLI
{schema_docs.format_plan_tool_usage(plan_tool_command=plan_tool_command)}
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
    schedule_digest: str,
    batch_index: int,
    batch_item_ids: list[str],
    deliverable_digest: str,
    deliverable_paths: list[str],
    output_goal_digest: str,
    embed_threshold: int,
    agent_context: ResolvedAgentContext | None = None,
    review_tool_command: str = "planning-review-tool",
) -> str:
    from top_down_planning.persistence import plan_path, render_schedule_path

    plan_file = plan_path(output_dir)
    schedule_file = render_schedule_path(output_dir)
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

## Render schedule digest
`{schedule_digest}`

## Deliverable output digest
`{deliverable_digest}`

{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## References
- Confirmed plan: {format_input_file_reference(plan_file, workspace)}
- Render schedule: {format_input_file_reference(schedule_file, workspace)}

## Workspace deliverables
{destination_lines}

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
    schedule_digest: str,
    deliverable_digest: str,
    deliverable_paths: list[str],
    output_goal_digest: str,
    embed_threshold: int,
    agent_context: ResolvedAgentContext | None = None,
    review_tool_command: str = "planning-review-tool",
) -> str:
    from top_down_planning.persistence import plan_path, render_schedule_path

    plan_file = plan_path(output_dir)
    schedule_file = render_schedule_path(output_dir)
    destination_lines = "\n".join(
        f"- {format_input_file_reference(workspace / relative_path, workspace)}"
        for relative_path in deliverable_paths
    ) or "- _No workspace deliverables were declared._"

    return f"""# Rendered output review session

Compare the confirmed plan, render schedule, workspace deliverables, and output goal.

Final deliverables live at their **workspace destination paths**.

Use `needs_revision` when targeted revision can fix deliverables.
Use `blocked` for unfixable tool/goal mismatches.

## Plan digest
`{plan_digest}`

## Output-goal digest
`{output_goal_digest}`

## Render schedule digest
`{schedule_digest}`

## Deliverable output digest
`{deliverable_digest}`

{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## References
- Confirmed plan: {format_input_file_reference(plan_file, workspace)}
- Render schedule: {format_input_file_reference(schedule_file, workspace)}

## Workspace deliverables
{destination_lines}

{schema_docs.format_review_schema_section(
    review_tool_command=review_tool_command,
    stage="rendered_output_review",
    plan_digest=plan_digest,
)}
"""
