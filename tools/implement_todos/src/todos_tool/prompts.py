"""Prompt builders for work and review Cursor sessions."""

from __future__ import annotations

from todos_tool.models import TodoItem

INSTRUCTION_DISCOVERY = """
## Mandatory instruction discovery

Before making changes or decisions, inspect applicable project instructions where present:

- AGENTS.md
- CLAUDE.md
- CONTRIBUTING.md
- README.md
- .cursor/rules/
- .cursor/skills/**/SKILL.md

Rules are mandatory when applicable. Skills are selected task-specific workflows.

You must:
1. Identify applicable global and scoped rules.
2. Select relevant skills only.
3. Follow required workflows and validation.
4. Re-check scoped rules when modifying new directories or file types.
5. Report instruction conflicts in your summary.

Do not skip this discovery process.
""".strip()


def build_work_prompt(
    item: TodoItem,
    *,
    logical_attempt: int,
    previous_feedback: str | None = None,
    continuation: str | None = None,
) -> str:
    criteria = "\n".join(f"- {c}" for c in item.acceptance_criteria)
    commands = "\n".join(f"- `{c}`" for c in item.validation.commands) or "- (none specified)"
    context_files = "\n".join(f"- {f}" for f in item.context.files) or "- (none specified)"

    parts = [
        "# Work session: implement one TODO item",
        "",
        INSTRUCTION_DISCOVERY,
        "",
        f"## Item `{item.id}`",
        f"**Title:** {item.title}",
        f"**Type:** {item.type.value}",
        f"**Logical attempt:** {logical_attempt}",
        "",
        "## Description",
        item.description.strip(),
        "",
        "## Acceptance criteria",
        criteria,
        "",
        "## Validation commands to run",
        commands,
        "",
        "## Context files",
        context_files,
        "",
        "## Requirements",
        "1. Inspect the current repository and applicable instructions/skills.",
        "2. Implement the requested change.",
        "3. Run targeted validation commands listed above.",
        "4. Leave the working tree ready for independent review.",
        "5. Return a concise summary of what changed and validation results.",
        "",
        "## Hard constraints",
        "- Do NOT commit.",
        "- Do NOT mark the item complete or edit todos item status to done.",
        "- Do NOT use `git add .` or `git add -A`.",
        "- If the item should be split/deferred/replaced, write a proposal JSON file to "
        f"`todos/runs/{item.id}/restructure-proposal.json` instead of silently weakening criteria.",
    ]

    if previous_feedback:
        parts.extend(
            [
                "",
                "## Previous review feedback",
                previous_feedback.strip(),
            ]
        )

    if continuation:
        parts.extend(
            [
                "",
                "## Continuation context (session restart)",
                continuation.strip(),
                "",
                "Inspect and preserve valid existing work. Continue from the current tree state.",
            ]
        )

    return "\n".join(parts)


def build_review_prompt(
    item: TodoItem,
    *,
    logical_attempt: int,
    work_summary: str | None,
    git_diff: str,
    git_status: str,
) -> str:
    criteria = "\n".join(f"- {c}" for c in item.acceptance_criteria)
    commands = "\n".join(f"- `{c}`" for c in item.validation.commands) or "- (none specified)"

    decision_schema = """
{
  "schema_version": 1,
  "item_id": "%s",
  "logical_attempt": %d,
  "decision": "pass" | "fail" | "blocked",
  "summary": "string",
  "acceptance_criteria": [
    {"criterion": "string", "passed": true, "evidence": "string"}
  ],
  "validation": [
    {"command": "string", "passed": true, "exit_code": 0, "summary": "string"}
  ],
  "instruction_compliance": {"passed": true, "violations": []},
  "issues": [],
  "recommended_next_action": "mark_done" | "retry" | "block"
}
""".strip() % (item.id, logical_attempt)

    return "\n".join(
        [
            "# Independent review session (read-only)",
            "",
            INSTRUCTION_DISCOVERY,
            "",
            "You are an independent reviewer. Remain read-only. Do not edit files or commit.",
            "",
            f"## Item `{item.id}`",
            f"**Title:** {item.title}",
            f"**Type:** {item.type.value}",
            f"**Logical attempt:** {logical_attempt}",
            "",
            "## Description",
            item.description.strip(),
            "",
            "## Acceptance criteria",
            criteria,
            "",
            "## Required validation commands",
            commands,
            "",
            "## Work summary from implementer",
            (work_summary or "(none provided)").strip(),
            "",
            "## Current git status",
            "```",
            git_status.strip() or "(clean)",
            "```",
            "",
            "## Current git diff",
            "```",
            git_diff.strip() or "(no diff)",
            "```",
            "",
            "## Your task",
            "Independently inspect the repository, instructions, rules/skills, diff, and validation.",
            "Return EXACTLY one JSON object matching this schema (no prose outside a JSON code fence):",
            "",
            "```json",
            decision_schema,
            "```",
            "",
            "A pass is valid only when every acceptance criterion passes, mandatory validation passes,",
            "instruction compliance passes, and no unresolved blocking issue exists.",
            "Map decisions: pass→mark_done, fail→retry, blocked→block.",
        ]
    )


def prompt_requires_instruction_discovery(prompt: str) -> bool:
    markers = (
        "AGENTS.md",
        ".cursor/rules/",
        ".cursor/skills",
        "Mandatory instruction discovery",
    )
    return all(marker in prompt for marker in markers)
