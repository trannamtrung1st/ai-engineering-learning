"""Construct bounded planning prompts for the agent."""

from __future__ import annotations

import json

from top_down_planning.models import PlanItem, PlanState


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
    input_text: str,
    output_goal: str,
    plan: PlanState,
    selected_items: list[PlanItem],
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

    return f"""# Top-down planning session

You are a planning agent. Analyze the selected planning items and return **only**
structured JSON operations. Do not rewrite the full plan state. Do not execute work.

## Output goal
{output_goal.strip()}

## Rules
- Choose exactly one operation per selected item.
- Use `expand` when the item still contains multiple meaningful planning concerns.
- Use `mark_actionable` when the item is detailed enough for the output goal.
- Use `mark_blocked` only when required information is missing and cannot be inferred safely.
- Use `mark_out_of_scope` when the item does not contribute to the output goal.
- Do not invent canonical item IDs. The tool assigns IDs.
- For sibling dependencies in an `expand`, use child `ref` values or existing item ids.
- Prefer breadth-first planning: keep major areas coherent before over-detailing one branch.

{feedback_block}## Input document
```markdown
{input_text.strip()}
```

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
