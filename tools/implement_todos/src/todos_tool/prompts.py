"""Prompt builders for work and review Cursor sessions."""

from __future__ import annotations

from todos_tool.models import TodoItem, ValidationCommandResult
from todos_tool.validation_runner import format_validation_results

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
    resolved_commands: list[str],
    todos_dir: str = "todos",
    previous_feedback: str | None = None,
    validation_failure_feedback: str | None = None,
    continuation: str | None = None,
    allow_full_check: bool = False,
) -> str:
    criteria = "\n".join(f"- {c}" for c in item.acceptance_criteria)
    command_lines = "\n".join(f"- `{c}`" for c in resolved_commands) or "- (none configured)"
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
        "## Authoritative validation commands (orchestrator-owned)",
        command_lines,
        "",
        "The orchestrator runs these commands once as the authoritative gate before review.",
        "Do NOT run the full authoritative check suite yourself unless this item is "
        "explicitly creating or bootstrapping that check.",
        "",
        "## Context files",
        context_files,
        "",
        "## Requirements",
        "1. Inspect the current repository and applicable instructions/skills.",
        "2. Implement the requested change.",
        "3. Use targeted local checks while editing (single tests, lint on touched files).",
        "4. Leave the working tree ready for independent review.",
        "5. Return a concise summary of what changed and any targeted checks you ran.",
        "",
        "## Hard constraints",
        "- Do NOT commit.",
        "- Do NOT mark the item complete or edit todos item status to done.",
        "- Do NOT use `git add .` or `git add -A`.",
        "- If the item should be split/deferred/replaced, write a proposal JSON file to "
        f"`{todos_dir}/runs/{item.id}/restructure-proposal.json` instead of silently "
        "weakening criteria.",
    ]

    if allow_full_check:
        parts.extend(
            [
                "",
                "## Setup exception",
                "This item may create or bootstrap the canonical project check. You may run "
                "the authoritative validation commands while establishing the check script.",
            ]
        )

    if validation_failure_feedback:
        parts.extend(
            [
                "",
                "## Authoritative validation failure (repair required)",
                validation_failure_feedback.strip(),
                "",
                "Fix the failures above. The orchestrator will rerun the authoritative gate "
                "after your repair work.",
            ]
        )

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
    resolved_commands: list[str],
    authoritative_validation: list[ValidationCommandResult] | None = None,
    prompt_only: bool = False,
    continuation: str | None = None,
) -> str:
    criteria = "\n".join(f"- {c}" for c in item.acceptance_criteria)
    command_lines = "\n".join(f"- `{c}`" for c in resolved_commands) or "- (none configured)"
    validation_text = (
        "(not executed in prompt-only dry run)"
        if prompt_only
        else (
            "(authoritative validation results unavailable)"
            if authoritative_validation is None
            else format_validation_results(authoritative_validation)
        )
    )

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
  "issues": [
    {"severity": "info", "title": "optional note", "detail": "non-blocking on pass"}
  ],
  "recommended_next_action": "mark_done" | "retry" | "block"
}
""".strip() % (item.id, logical_attempt)

    parts = [
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
        command_lines,
        "",
        "## Authoritative orchestrator validation",
        validation_text,
        "",
        "These results were produced outside the Cursor sessions. Treat them as authoritative.",
        "Copy each command, passed value, and exit_code exactly into your JSON decision.",
        "Do NOT rerun validation commands. Inspect code, diffs, and the supplied output only.",
        "",
        "## Work summary from implementer",
        (work_summary or "(none provided)").strip(),
    ]

    parts.extend(
        [
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
        ]
    )

    if continuation:
        parts.extend(
            [
                "",
                "## Continuation context (session restart)",
                continuation.strip(),
            ]
        )

    parts.extend(
        [
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
            "Use `issues` for notes. Structured issues may use severity info/low (non-blocking on pass)",
            "or medium/high/critical (blocking). Plain-string issues are treated as blocking.",
            "Map decisions: pass→mark_done, fail→retry, blocked→block.",
        ]
    )
    return "\n".join(parts)


def prompt_requires_instruction_discovery(prompt: str) -> bool:
    markers = (
        "AGENTS.md",
        ".cursor/rules/",
        ".cursor/skills",
        "Mandatory instruction discovery",
    )
    return all(marker in prompt for marker in markers)
