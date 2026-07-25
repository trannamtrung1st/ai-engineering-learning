"""Construct bounded planning prompts for the agent."""

from __future__ import annotations

import json
from pathlib import Path

from top_down_planning.agent_context import ResolvedAgentContext
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.models import PlanItem, PlanState, WholePlanContextMode
from top_down_planning.render_brief import actionable_leaf_items, build_render_brief


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
  "type": "expand | mark_actionable | mark_blocked | mark_out_of_scope",
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


def _format_render_brief_section(
    *,
    plan: PlanState,
    render_brief_file: Path | None,
    workspace: Path,
    embed_threshold: int,
) -> str:
    brief = build_render_brief(plan)
    leaf_count = len(actionable_leaf_items(plan))
    header = (
        f"The decomposition produced **{leaf_count} actionable deliverable unit(s)**. "
        "Every unit below must appear in the final output. Use the output goal only "
        "to decide file format, schema, and naming — not to add, remove, merge, or "
        "re-scope items."
    )
    if render_brief_file is not None and not should_embed_content(
        brief, embed_threshold=embed_threshold
    ):
        return (
            f"{header}\n\n"
            "Read the full render brief before writing deliverables:\n\n"
            f"{format_input_file_reference(render_brief_file, workspace)}\n\n"
            "Open and read that file in full. It is derived from the canonical "
            "planning breakdown and defines the required scope."
        )
    return f"{header}\n\n{format_embedded_markdown(brief)}"


def build_final_render_prompt(
    *,
    loaded_input: LoadedInput,
    plan_file: Path,
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan: PlanState,
    embed_threshold: int,
    render_brief_file: Path | None = None,
    validation_feedback: list[str] | None = None,
    agent_context: ResolvedAgentContext | None = None,
) -> str:
    """Build the prompt for the post-decomposition render phase."""
    input_section = format_input_document_section(
        loaded_input=loaded_input,
        workspace=workspace,
        embed_threshold=embed_threshold,
    )
    brief_section = _format_render_brief_section(
        plan=plan,
        render_brief_file=render_brief_file,
        workspace=workspace,
        embed_threshold=embed_threshold,
    )
    feedback_block = ""
    if validation_feedback:
        feedback_block = (
            "## Render validation feedback from previous attempt\n"
            + "\n".join(f"- {error}" for error in validation_feedback)
            + "\n\nFix every issue. Regenerate deliverables from the breakdown; "
            "do not copy prior files.\n\n"
        )
    deliverable_dir = output_dir.resolve()
    try:
        deliverable_display = str(
            deliverable_dir.relative_to(workspace.resolve())
        ).replace("\\", "/")
    except ValueError:
        deliverable_display = str(deliverable_dir)
    return f"""# Final planning render

Decomposition is complete. Produce the **final user-facing deliverable file(s)**.

You are a planning renderer, not an executor. Transform the completed breakdown into
deliverables that satisfy the output goal. Do not execute implementation work.

## Roles of each input

1. **Breakdown (authoritative scope)** — which items exist, their order, dependencies,
   expected outputs, acceptance criteria, blocked items, and open questions.
2. **Output goal (authoritative format)** — deliverable schema, filenames, terminology,
   validation rules, and presentation requirements.
3. **Primary input (background context only)** — source intent and domain detail for
   filling in format-specific fields. It must not override or replace breakdown items.

{feedback_block}{_format_agent_context_section(agent_context)}## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

Use the output goal to decide:
- deliverable format(s) and filename(s);
- structure, terminology, and required sections;
- how to map each breakdown unit into the requested schema.

If the output goal mentions an example path (for example `plans/.../todos/`), treat
that as a format reference only. Write new deliverables under the deliverable
directory below unless the output goal defines an **Output artifacts** section with
exact paths.

## Deliverable directory
Write all deliverables here:

{format_input_file_reference(deliverable_dir, workspace)}

Prefer `{deliverable_display}/` over paths cited only as examples inside the output goal.

Internal planning state lives under `{output_dir / ".planning-output"}`. Do not write
deliverables there or modify files under `.planning-output/`.

## Breakdown to render
{brief_section}

## Source documents

Primary input (background context only):

{input_section}

Canonical planning state (full breakdown source):

{format_input_file_reference(plan_file, workspace)}

Open and read `plan.yaml` when you need fields not shown in the render brief.

## Planning result metadata
- Status: {plan.result.status.value}
- Summary: {plan.result.summary or "No summary provided."}
- Actionable deliverable units: {len(actionable_leaf_items(plan))}

## Instructions
- Treat the breakdown as the scope contract: cover **every actionable deliverable unit**
  exactly once in the final output.
- Do **not** copy, restore, or reuse pre-existing files from git history or from paths
  mentioned in the output goal. Generate fresh deliverables from the breakdown.
- Do **not** add, remove, merge, or re-scope items beyond what the breakdown defines.
- When the output goal implies one file per checkpoint/item, create one deliverable per
  actionable leaf unit in breakdown order.
- Preserve each unit's objective, dependencies, expected outputs, acceptance criteria,
  blocked reasons, and open questions.
- When the output goal uses per-item title fields (for example YAML `title:`), copy each
  breakdown unit title **verbatim** from the render brief. Do not rephrase, add commas,
  em-dashes, or other punctuation for readability.
- Do not return structured JSON or a chat-only summary instead of writing files.
- Do not modify, delete, or recreate any file under `.planning-output/`, especially
  `plan.yaml`.
- Do not include orchestration internals such as item IDs unless the output goal
  requires them.
"""
