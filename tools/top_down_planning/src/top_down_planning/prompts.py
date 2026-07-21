"""Construct bounded planning prompts for the agent."""

from __future__ import annotations

import json
from pathlib import Path

from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.models import PlanItem, PlanState


def should_embed_content(text: str, *, embed_threshold: int) -> bool:
    """Return True when content is short enough to inline in the prompt."""
    return len(text.strip()) <= embed_threshold


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


def format_output_goal_section(
    *,
    output_goal: LoadedOutputGoal,
    workspace: Path,
    embed_threshold: int,
) -> str:
    text = output_goal.text.strip()
    if should_embed_content(text, embed_threshold=embed_threshold):
        return text
    if output_goal.path is not None:
        return (
            "Read the output goal specification before planning:\n\n"
            f"{format_input_file_reference(output_goal.path, workspace)}\n\n"
            "Open and read that file in full. It defines the desired final plan "
            "shape, actionability criteria, and rendering expectations."
        )
    return text


def format_stop_hint_section(
    *,
    stop_hint: LoadedStopHint,
    workspace: Path,
    embed_threshold: int,
) -> str:
    text = stop_hint.text.strip()
    if should_embed_content(text, embed_threshold=embed_threshold):
        return text
    if stop_hint.path is not None:
        return (
            "Read the expansion stop guidance before deciding whether to expand or stop:\n\n"
            f"{format_input_file_reference(stop_hint.path, workspace)}\n\n"
            "Open and read that file in full. Use it when choosing `expand`, "
            "`mark_actionable`, and `assessment.plan_complete`."
        )
    return text


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
            f"```markdown\n{text}\n```"
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


def _branch_summary(plan: PlanState, exclude_ids: set[str]) -> str:
    lines: list[str] = []
    for item in sorted(plan.plan, key=lambda i: i.order):
        if item.id in exclude_ids:
            continue
        if item.decomposition_status.value == "needs_expansion":
            continue
        lines.append(
            f"- [{item.id}] {item.title} ({item.decomposition_status.value})"
        )
    if not lines:
        return "No other established branches yet."
    return "\n".join(lines[:40])


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
    stop_hint: LoadedStopHint | None = None,
    validation_feedback: list[str] | None = None,
) -> str:
    selected_ids = {item.id for item in selected_items}
    contexts = [_format_item_context(plan, item) for item in selected_items]
    operation_schema = {
        "assessment": {
            "plan_complete": "boolean",
            "summary": "string",
        },
        "operations": [
            {
                "type": "expand | mark_actionable | mark_blocked | mark_out_of_scope",
                "node_id": "one of the selected item ids",
                "reason": "string",
                "children": [
                    {
                        "ref": "optional local reference like child-1",
                        "title": "string",
                        "objective": "string",
                        "dependencies": ["child refs or existing item ids"],
                        "expected_outputs": ["string"],
                        "acceptance_criteria": ["string"],
                    }
                ],
            }
        ],
    }

    feedback_block = ""
    if validation_feedback:
        feedback_block = (
            "## Validation feedback from previous attempt\n"
            + "\n".join(f"- {error}" for error in validation_feedback)
            + "\n\nFix every issue and return a valid response.\n\n"
        )

    stop_hint_block = ""
    if stop_hint is not None:
        stop_hint_block = (
            "## Expansion stop guidance\n"
            "Use this when deciding whether to `expand`, `mark_actionable`, or set "
            "`assessment.plan_complete` to true:\n\n"
            f"{format_stop_hint_section(stop_hint=stop_hint, workspace=workspace, embed_threshold=embed_threshold)}\n\n"
        )

    return f"""# Top-down planning session

You are a planning agent. Analyze the selected planning items and return **only**
structured JSON operations. Do not rewrite the full plan state. Do not execute work.

## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

{stop_hint_block}## Rules
- Choose exactly one operation per selected item.
- Use `expand` when the item still contains multiple meaningful planning concerns.
- Use `mark_actionable` when the item is detailed enough for the output goal.
- Use `mark_blocked` only when required information is missing and cannot be inferred safely.
- Use `mark_out_of_scope` when the item does not contribute to the output goal.
- Set `assessment.plan_complete` to true only when every relevant item is sufficiently
  detailed for the output goal and no further expansion is warranted.
- Do not invent canonical item IDs. The tool assigns IDs.
- For sibling dependencies in an `expand`, use child `ref` values or existing item ids.
- Prefer breadth-first planning: keep major areas coherent before over-detailing one branch.

{feedback_block}## Input document

{format_input_document_section(loaded_input=loaded_input, workspace=workspace, embed_threshold=embed_threshold)}

## Other established branches
{_branch_summary(plan, selected_ids)}

## Selected items
{chr(10).join(contexts)}

## Required response format
Return one JSON object matching this schema:

```json
{json.dumps(operation_schema, indent=2)}
```

Return the JSON inside a ```json fenced block or as raw JSON. No prose outside the JSON.
"""


def build_final_render_prompt(
    *,
    loaded_input: LoadedInput,
    plan_file: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan: PlanState,
    embed_threshold: int,
) -> str:
    """Build the prompt for the post-decomposition render phase."""
    artifact_schema = {
        "artifacts": [
            {
                "relative_path": "filename relative to --output, e.g. implementation-plan.md",
                "content": "full file contents as a string",
            }
        ]
    }
    input_section = format_input_document_section(
        loaded_input=loaded_input,
        workspace=workspace,
        embed_threshold=embed_threshold,
    )
    return f"""# Final planning render

Decomposition is complete. Produce the **final user-facing deliverable file(s)**.

You are a planning renderer, not an executor. Read the canonical planning state and
render deliverables according to the output goal. Do not invent new planning items,
change statuses, or execute work.

## Output goal
{format_output_goal_section(output_goal=output_goal, workspace=workspace, embed_threshold=embed_threshold)}

Follow that specification for:
- deliverable format(s) and filename(s);
- structure, terminology, and required sections;
- actionability presentation.

If the output goal defines an **Output artifacts** section, follow it exactly for
paths and formats. Otherwise choose sensible filenames and formats that match the goal.

## Source documents

Primary input (for context only):

{input_section}

Canonical planning state (authoritative):

{format_input_file_reference(plan_file, workspace)}

Open and read `plan.yaml` in full. It contains every planning item, dependency,
status, expected output, acceptance criterion, blocked reason, and open question.

## Planning result metadata
- Status: {plan.result.status.value}
- Summary: {plan.result.summary or "No summary provided."}

## Required response format
Return one JSON object describing every generated deliverable:

```json
{json.dumps(artifact_schema, indent=2)}
```

Rules:
- Return the JSON inside a ```json fenced block or as raw JSON.
- Write one or more artifacts depending on the output goal.
- Use only relative paths under the output directory.
- Do not write into `.planning-output/`.
- Do not include orchestration internals such as item IDs unless the output goal
  calls for them.
- Preserve hierarchy, ordering, expected outputs, dependencies, acceptance criteria,
  blocked items, and open questions from the canonical state.
"""
