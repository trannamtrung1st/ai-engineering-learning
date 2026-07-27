"""Construct bounded planning prompts for the agent."""

from __future__ import annotations

import json
from pathlib import Path

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


def format_plan_tool_section(*, plan_tool_command: str = "planning-plan-tool") -> str:
    """Describe the session transaction CLI the agent must invoke."""
    return f"""Use the planning transaction CLI — do **not** return JSON in chat and do **not**
edit `.planning-output/plan.yaml` directly. Session scope is already configured in the
environment (`PLANNING_TOOL_TXN_FILE`, `PLANNING_TOOL_SELECTED_IDS`, `PLANNING_TOOL_PLAN_FILE`,
`PLANNING_TOOL_PLAN_DIGEST`).

Your **writable scope** is limited to the assigned generation items listed below.
The whole-plan context is read-only reference material.

Workflow:
1. Read the complete plan overview (embedded below or at the referenced path).
2. Optionally run `{plan_tool_command} show-context` for selected-node details.
3. Optionally run `{plan_tool_command} status` to inspect the current draft.
4. For **each assigned item**, run `{plan_tool_command} record-operation --json '<operation>'`.
5. Run `{plan_tool_command} set-assessment [--plan-complete|--no-plan-complete] --summary "..."`.
6. Run `{plan_tool_command} finalize` to commit the session transaction.

Operation JSON schema (one object per `record-operation` call):

```json
{{
  "type": "expand | mark_actionable | mark_blocked | mark_out_of_scope | revise_actionable",
  "node_id": "one of the selected item ids",
  "reason": "string",
  "children": [
    {{
      "ref": "optional local reference like child-1",
      "title": "string",
      "objective": "string",
      "dependencies": ["child refs or existing item ids"],
      "expected_outputs": ["string"],
      "acceptance_criteria": ["string"]
    }}
  ]
}}
```

For `revise_actionable`, provide the full updated `expected_outputs` and
`acceptance_criteria` lists (not partial deltas). Optional `title`, `objective`,
and `dependencies` replace the existing values when provided.

For `mark_actionable`, include `expected_outputs` and `acceptance_criteria` when required by
the output goal. For `mark_blocked`, include `missing_information` and `open_question`.

For a child-count constraint conflict, use `mark_blocked` with:
`constraint_code: "max_children_exceeded"` and `required_min_children` set to the required
direct-child count (greater than the configured limit)."""


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
{format_plan_tool_section(plan_tool_command=plan_tool_command)}
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
{format_plan_tool_section(plan_tool_command=plan_tool_command)}
"""


def format_render_node_tool_section(
    *,
    render_tool_command: str = "planning-render-tool",
) -> str:
    return f"""Use the render transaction CLI — do **not** write deliverables directly
to workspace destinations.

Workflow:
1. Run `{render_tool_command} begin --node-id <id> --context-digest <digest>`.
2. Record exactly one decision with `{render_tool_command} record-decision --decision produce|skip|defer`.
3. For `produce`, declare artifacts with `{render_tool_command} declare-artifact --json '<intent>'`
   and stage content with `{render_tool_command} stage-artifact --artifact-key <key> --content-file <path>`.
4. Run `{render_tool_command} submit` to hand the candidate to the coordinator.

Artifact intent JSON schema:
```json
{{
  "artifact_key": "feature-guest-checkout",
  "path": "backlog/features/guest-checkout.md",
  "location": "final",
  "operation": "create",
  "owner_kind": "node",
  "owner_id": "item-012"
}}
```
"""


def build_render_node_prompt(
    *,
    node_id: str,
    plan_digest: str,
    output_goal_digest: str,
    render_config_digest: str,
    node_context_markdown: str,
    output_goal: LoadedOutputGoal,
    workspace: Path,
    embed_threshold: int,
    validation_feedback: list[str] | None = None,
    agent_context: ResolvedAgentContext | None = None,
    render_tool_command: str = "planning-render-tool",
) -> str:
    feedback_block = ""
    if validation_feedback:
        feedback_block = (
            "## Validation feedback from previous attempt\n"
            + "\n".join(f"- {error}" for error in validation_feedback)
            + "\n\nFix every issue before submitting the node transaction.\n\n"
        )
    return f"""# Render node session: {node_id}

Decide whether this plan node should produce, skip, or defer artifacts.

## Plan digest
`{plan_digest}`

## Output-goal digest
`{output_goal_digest}`

## Render-config digest
`{render_config_digest}`

{feedback_block}{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## Node context
{node_context_markdown}

{format_render_node_tool_section(render_tool_command=render_tool_command)}

## Instructions
- Record exactly one `produce`, `skip`, or `defer` decision with a reason when skipping or deferring.
- Stage candidate content only in the assigned private staging directory.
- Submit the node transaction before ending the session.
- Do not modify canonical planning files.
"""


def build_render_output_review_prompt(
    *,
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan_digest: str,
    manifest_digest: str,
    deliverable_digest: str,
    deliverable_paths: list[str],
    output_goal_digest: str,
    embed_threshold: int,
    agent_context: ResolvedAgentContext | None = None,
    review_tool_command: str = "planning-review-tool",
) -> str:
    from top_down_planning.persistence import (
        plan_path,
        render_assembled_dir,
        render_manifest_path,
    )

    plan_file = plan_path(output_dir)
    manifest_file = render_manifest_path(output_dir)
    assembled_dir = render_assembled_dir(output_dir)
    destination_lines = "\n".join(
        f"- {format_input_file_reference(workspace / relative_path, workspace)}"
        for relative_path in deliverable_paths
    ) or "- _No workspace deliverables were declared._"

    return f"""# Rendered output review session

Compare the confirmed plan, render manifest, workspace deliverables, intermediate staging, and
output goal.

Final deliverables live at their **workspace destination paths**. Intermediate artifacts under
`.planning-output/render/assembled/intermediates/` are synthesis inputs only.

Use `needs_rerender` for node output that can be fixed by rerunning the affected render
nodes. Use `blocked` for unfixable tool/goal mismatches that cannot be corrected by rerender alone.

## Plan digest
`{plan_digest}`

## Output-goal digest
`{output_goal_digest}`

## Render manifest digest
`{manifest_digest}`

## Deliverable output digest
`{deliverable_digest}`

{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

## References
- Confirmed plan: {format_input_file_reference(plan_file, workspace)}
- Render manifest: {format_input_file_reference(manifest_file, workspace)}
- Intermediate staging directory: {format_input_file_reference(assembled_dir, workspace)}

## Workspace deliverables
{destination_lines}

Use `{review_tool_command} set-result --json '<result>'` then `{review_tool_command} finalize`.

Result JSON schema:
```json
{{
  "stage": "rendered_output_review",
  "plan_digest": "{plan_digest}",
  "output_goal_digest": "{output_goal_digest}",
  "render_manifest_digest": "{manifest_digest}",
  "deliverable_output_digest": "{deliverable_digest}",
  "decision": "approve | needs_rerender | blocked",
  "summary": "...",
  "findings": [],
  "affected_node_ids": []
}}
```
"""
