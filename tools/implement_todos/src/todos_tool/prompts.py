"""Prompt builders for work, review, and YAML repair Cursor sessions."""

from __future__ import annotations

from typing import Any

from todos_tool.models import TodoItem, ValidationCommandResult, EvidenceCommandResult
from todos_tool.agent_context import ResolvedAgentContext
from todos_tool.project_context import ProjectContext, ResolvedContextFile
from todos_tool.validation_runner import format_validation_results
from todos_tool.evidence_runner import format_evidence_results

LONG_RUNNING_COMMANDS = """
# Long-running commands

- Run potentially long commands in the tool-managed background; never use
  shell `&`, `nohup`, or another detached process.
- Continue independent work while a background command runs.
- Check every background command before ending the session.
- If a command exceeds its expected runtime, inspect its latest output and
  process activity before deciding it is hung.
- If it is hung, terminate its complete process tree and record the command as
  failed or inconclusive. A killed command is not passing evidence.
- Never emit the final driver signal while a shell command is still running.
""".strip()


def _join_parts(parts: list[str]) -> str:
    return "\n".join(part for part in parts if part is not None and part != "")


def _bullet_lines(items: list[str]) -> str:
    lines = [f"- {item.strip()}" for item in items if item and str(item).strip()]
    return "\n".join(lines)


def _optional_section(title: str, body: str | None) -> list[str]:
    if body is None or not body.strip():
        return []
    return ["", f"## {title}", body.strip()]


def _render_project_context(
    project_context: ProjectContext | None,
    resolved_context_files: list[ResolvedContextFile] | None,
) -> list[str]:
    ctx = project_context or ProjectContext.neutral()
    resolved = resolved_context_files or []
    if not ctx.context_files and not ctx.instructions and not resolved:
        return []

    parts: list[str] = ["", "## Repository context"]
    if resolved:
        file_lines = []
        for entry in resolved:
            suffix = ""
            if not entry.exists:
                suffix = " (missing)"
            req = " required" if entry.required else ""
            file_lines.append(f"- `{entry.path}`{req}{suffix}")
        parts.extend(["", "### Context files", "\n".join(file_lines)])
    elif ctx.context_files:
        parts.extend(
            [
                "",
                "### Context files",
                _bullet_lines([ref.path for ref in ctx.context_files]),
            ]
        )

    if ctx.instructions:
        parts.extend(["", "### Instructions", _bullet_lines(list(ctx.instructions))])

    parts.extend(
        [
            "",
            "Read applicable context files before making edits or decisions.",
        ]
    )
    return parts


def _render_agent_context(resolved: ResolvedAgentContext | None) -> list[str]:
    if resolved is None or (not resolved.skills and not resolved.rules):
        return []
    parts: list[str] = ["", "## Agent context"]
    if resolved.skills:
        lines = [f"- `{path}`" for path in resolved.skills]
        parts.extend(
            [
                "",
                "### Applicable skills",
                "\n".join(lines),
                "",
                "Read each listed skill file before acting and follow its guidance.",
            ]
        )
    if resolved.rules:
        lines = [f"- `{path}`" for path in resolved.rules]
        parts.extend(
            [
                "",
                "### Applicable rules",
                "\n".join(lines),
                "",
                "Read each listed rule file before acting and apply its constraints.",
            ]
        )
    return parts


def _render_manifest_policy(
    *,
    authority: list[str] | None,
    hard_rules: list[str] | None,
    stop_conditions: list[str] | None,
    out_of_scope: str | None,
) -> list[str]:
    parts: list[str] = []
    if authority:
        parts.extend(_optional_section("Authority", _bullet_lines(authority)))
    if hard_rules:
        parts.extend(_optional_section("Hard rules", _bullet_lines(hard_rules)))
    if stop_conditions:
        parts.extend(_optional_section("Stop conditions", _bullet_lines(stop_conditions)))
    if out_of_scope and out_of_scope.strip():
        parts.extend(_optional_section("Out of scope", out_of_scope.strip()))
    return parts


def _render_item_contract(
    *,
    contract_refs: list[str] | None,
    checklist: list[dict[str, Any]] | None,
    item_context_files: list[str],
) -> list[str]:
    parts: list[str] = []
    if contract_refs:
        parts.extend(_optional_section("Contract references", _bullet_lines(contract_refs)))
    if checklist:
        lines = []
        for entry in checklist:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("item") or entry.get("text") or entry.get("id") or "").strip()
            if not label:
                continue
            done = entry.get("done")
            status = entry.get("status")
            if done is True or status == "done":
                state = "done"
            elif done is False or status in {"pending", "open"}:
                state = "open"
            else:
                state = str(status or "unknown")
            lines.append(f"- [{state}] {label}")
        if lines:
            parts.extend(["", "## Checklist", "\n".join(lines)])
    if item_context_files:
        parts.extend(
            _optional_section("Item context files", _bullet_lines(item_context_files))
        )
    return parts


def _render_evidence_commands(item: TodoItem) -> list[str]:
    if not item.evidence.commands:
        return []
    lines: list[str] = []
    for spec in item.evidence.commands:
        line = f"- command: `{spec.command}`"
        if spec.cwd and spec.cwd != ".":
            line += f"  cwd: `{spec.cwd}`"
        if spec.timeout_seconds is not None:
            line += f"  timeout_seconds: {spec.timeout_seconds}"
        lines.append(line)
    return ["", "## Completion evidence commands", "\n".join(lines)]


def build_work_prompt(
    item: TodoItem,
    *,
    logical_attempt: int,
    resolved_commands: list[str],
    todos_dir: str = "todos",
    project_context: ProjectContext | None = None,
    resolved_context_files: list[ResolvedContextFile] | None = None,
    authority: list[str] | None = None,
    hard_rules: list[str] | None = None,
    stop_conditions: list[str] | None = None,
    out_of_scope: str | None = None,
    contract_refs: list[str] | None = None,
    checklist: list[dict[str, Any]] | None = None,
    previous_feedback: str | None = None,
    validation_failure_feedback: str | None = None,
    evidence_failure_feedback: str | None = None,
    evidence_mode: str = "captured",
    continuation: str | None = None,
    allow_full_check: bool = False,
    agent_context: ResolvedAgentContext | None = None,
) -> str:
    criteria = _bullet_lines(item.acceptance_criteria)
    command_lines = _bullet_lines([f"`{c}`" for c in resolved_commands])

    parts = [
        "# Work session: implement one TODO item",
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
    ]
    parts.extend(_render_item_contract(
        contract_refs=contract_refs,
        checklist=checklist,
        item_context_files=item.context.files,
    ))
    parts.extend(_render_manifest_policy(
        authority=authority,
        hard_rules=hard_rules,
        stop_conditions=stop_conditions,
        out_of_scope=out_of_scope,
    ))
    parts.extend(_render_project_context(project_context, resolved_context_files))
    parts.extend(_render_agent_context(agent_context))
    parts.extend(_render_evidence_commands(item))

    if item.evidence.commands:
        if evidence_mode == "driver":
            parts.extend(
                [
                    "",
                    "## Completion evidence mode: driver",
                    "The orchestrator executes the completion evidence commands after this "
                    "session. Do NOT duplicate those commands yourself.",
                ]
            )
        else:
            parts.extend(
                [
                    "",
                    "## Completion evidence mode: captured",
                    "Run each completion evidence command exactly as declared:",
                    "- Pass the literal YAML `command` string to the shell tool.",
                    "- Set the shell tool working-directory field to the declared `cwd` "
                    "(omit or use repository root when cwd is `.`).",
                    "- Do not prefix commands with `cd … &&`, pipelines, shell wrappers, "
                    "or extra chained commands.",
                ]
            )

    if command_lines:
        parts.extend(
            [
                "",
                "## Authoritative validation commands (orchestrator-owned)",
                command_lines,
                "",
                "The orchestrator runs these commands once as the authoritative gate before review.",
                "Do NOT run the full authoritative check suite yourself unless this item is "
                "explicitly creating or bootstrapping that check.",
            ]
        )

    parts.extend(
        [
            "",
            LONG_RUNNING_COMMANDS,
            "",
            "## Requirements",
            "1. Inspect the current repository and applicable context/instructions.",
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
    )

    if allow_full_check:
        parts.extend(
            [
                "",
                "## Setup exception",
                "This item may create or bootstrap the canonical project check. You may run "
                "the authoritative validation commands while establishing the check script.",
            ]
        )

    if item.allow_empty_commit:
        parts.extend(
            [
                "",
                "## Git finalize",
                "This item may complete with **no tracked repository changes**. Deliverables "
                "may live under gitignored paths (for example `temp/`). Do not force tracked "
                "edits solely to produce a commit. When you do change tracked source files, "
                "leave them ready for the orchestrator commit step.",
            ]
        )
    else:
        parts.extend(
            [
                "",
                "## Git finalize requirement",
                "This item **requires tracked repository changes**. Do not finish with only "
                "gitignored or todos metadata updates.",
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

    if evidence_failure_feedback:
        parts.extend(
            [
                "",
                "## Completion evidence failure (repair required)",
                evidence_failure_feedback.strip(),
                "",
                "Fix the issues above and rerun the declared completion evidence commands "
                "exactly before ending the session.",
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

    return _join_parts(parts)


def format_review_tool_section(*, review_tool_command: str = "todos-review-tool") -> str:
    """Describe the session review CLI the agent must invoke."""
    return f"""Use the review submission CLI — do **not** return JSON in chat and do **not**
edit repository files. Session scope is already configured in the environment
(`TODOS_TOOL_REVIEW_SUBMISSION_FILE`, `TODOS_TOOL_ITEM_ID`, `TODOS_TOOL_LOGICAL_ATTEMPT`).

Workflow:
1. Optionally run `{review_tool_command} status` to inspect the current submission state.
2. Run `{review_tool_command} submit --json '<decision>'` with one review decision object.
3. Confirm with `{review_tool_command} status` that the submission artifact exists.

You are read-only except for `{review_tool_command}`. Do NOT rerun validation commands
or other repository shell commands. You MUST submit through `{review_tool_command}`."""


def build_review_prompt(
    item: TodoItem,
    *,
    logical_attempt: int,
    work_summary: str | None,
    git_diff: str,
    git_status: str,
    resolved_commands: list[str],
    project_context: ProjectContext | None = None,
    resolved_context_files: list[ResolvedContextFile] | None = None,
    authority: list[str] | None = None,
    hard_rules: list[str] | None = None,
    stop_conditions: list[str] | None = None,
    out_of_scope: str | None = None,
    contract_refs: list[str] | None = None,
    checklist: list[dict[str, Any]] | None = None,
    authoritative_validation: list[ValidationCommandResult] | None = None,
    authoritative_evidence: list[EvidenceCommandResult] | None = None,
    prompt_only: bool = False,
    continuation: str | None = None,
    commit_hint: str | None = None,
    review_tool_command: str = "todos-review-tool",
    agent_context: ResolvedAgentContext | None = None,
) -> str:
    criteria = _bullet_lines(item.acceptance_criteria)
    command_lines = _bullet_lines([f"`{c}`" for c in resolved_commands])
    validation_text = (
        "(not executed in prompt-only dry run)"
        if prompt_only
        else (
            "(authoritative validation results unavailable)"
            if authoritative_validation is None
            else format_validation_results(authoritative_validation)
        )
    )
    evidence_text = (
        "(not executed in prompt-only dry run)"
        if prompt_only
        else (
            "(authoritative completion evidence unavailable)"
            if authoritative_evidence is None
            else format_evidence_results(authoritative_evidence)
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
  "evidence": [
    {"command": "string", "cwd": ".", "passed": true, "exit_code": 0, "summary": "string"}
  ],
  "instruction_compliance": {"passed": true, "violations": []},
  "issues": [
    {"severity": "info", "title": "optional note", "detail": "non-blocking on pass"}
  ],
  "proposed_commit_message": "agent: feat: concise subject",
  "recommended_next_action": "mark_done" | "retry" | "block"
}
""".strip() % (item.id, logical_attempt)

    parts = [
        "# Independent review session (read-only)",
        "",
        "You are an independent reviewer. Do not edit repository files or commit.",
        "Submit your decision only through the review submission CLI described below.",
        "",
        f"## Item `{item.id}`",
        f"**Title:** {item.title}",
        f"**Type:** {item.type.value}",
        f"**Logical attempt:** {logical_attempt}",
    ]
    if item.allow_empty_commit:
        parts.extend(
            [
                "",
                "**Finalize mode:** allow empty (default) — deliverables may be gitignored-only; "
                "pass is valid when there are no trackable source changes and HEAD is unchanged.",
            ]
        )
    else:
        parts.extend(
            [
                "",
                "**Finalize mode:** commit required — pass expects trackable source changes and "
                "a non-empty `proposed_commit_message`.",
            ]
        )
    parts.extend(
        [
            "",
            "## Description",
            item.description.strip(),
            "",
            "## Acceptance criteria",
            criteria,
        ]
    )
    parts.extend(_render_item_contract(
        contract_refs=contract_refs,
        checklist=checklist,
        item_context_files=item.context.files,
    ))
    parts.extend(_render_manifest_policy(
        authority=authority,
        hard_rules=hard_rules,
        stop_conditions=stop_conditions,
        out_of_scope=out_of_scope,
    ))
    parts.extend(_render_project_context(project_context, resolved_context_files))
    parts.extend(_render_agent_context(agent_context))

    if command_lines:
        parts.extend(
            [
                "",
                "## Required validation commands",
                command_lines,
            ]
        )

    parts.extend(
        [
            "",
            "## Authoritative orchestrator validation",
            validation_text,
            "",
            "These results were produced outside the Cursor sessions. Treat them as authoritative.",
            "Copy each command, passed value, and exit_code exactly into your JSON decision.",
            "Do NOT rerun validation commands. Inspect code, diffs, and the supplied output only.",
            "",
            "## Authoritative completion evidence",
            evidence_text,
            "",
            "These results were produced outside the Cursor sessions for item "
            "evidence.commands. Copy each command, cwd, passed value, and exit_code "
            "exactly into your JSON decision. Do not run repository shell commands "
            "during review except the review submission CLI.",
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

    if commit_hint and commit_hint.strip():
        parts.extend(
            [
                "",
                "## Commit subject guidance",
                commit_hint.strip(),
                "",
                "When decision is pass, set `proposed_commit_message` to the exact full "
                "commit subject the orchestrator should use.",
            ]
        )
    elif item.allow_empty_commit:
        parts.extend(
            [
                "",
                "## Commit subject guidance",
                "When there are trackable changes to commit, set `proposed_commit_message` to "
                "the exact full commit subject the orchestrator should use. When there are no "
                "trackable changes, omit `proposed_commit_message` or set it to null.",
            ]
        )

    commit_message_rule = (
        "On pass, `proposed_commit_message` may be omitted or null when there are no "
        "trackable changes to commit; otherwise it must be a non-empty full commit subject."
        if item.allow_empty_commit
        else "On pass, `proposed_commit_message` must be a non-empty full commit subject."
    )

    parts.extend(
        [
            "",
            "## Review submission tool",
            format_review_tool_section(review_tool_command=review_tool_command),
            "",
            "Submit EXACTLY one JSON object matching this schema:",
            "",
            "```json",
            decision_schema,
            "```",
            "",
            "A pass is valid only when every acceptance criterion passes, mandatory validation passes,",
            "instruction compliance passes, and no unresolved blocking issue exists.",
            commit_message_rule,
            "Use `issues` for notes. Structured issues may use severity info/low (non-blocking on pass)",
            "or medium/high/critical (blocking). Plain-string issues are treated as blocking.",
            "Map decisions: pass→mark_done, fail→retry, blocked→block.",
        ]
    )
    return _join_parts(parts)


def build_repair_prompt(
    *,
    diagnostic: str,
    todos_dir: str,
    yaml_files: list[str],
    project_context: ProjectContext | None = None,
    resolved_context_files: list[ResolvedContextFile] | None = None,
    authoring_guide_path: str | None = None,
    schema_module: str = "todos_tool.manifest",
) -> str:
    file_lines = _bullet_lines(yaml_files) or "- (none discovered)"
    parts = [
        "# YAML repair session (TODO set only)",
        "",
        "Repair malformed TODO-set YAML so the driver can reload and validate the work package.",
        "",
        "## Loader diagnostic",
        diagnostic.strip(),
        "",
        "## TODO set location",
        f"Directory: `{todos_dir}`",
        "",
        "## Candidate YAML files",
        file_lines,
    ]
    parts.extend(_render_project_context(project_context, resolved_context_files))

    if authoring_guide_path:
        parts.extend(
            [
                "",
                "## Authoring guide",
                f"Read `{authoring_guide_path}` for schema semantics and completion behavior.",
            ]
        )

    parts.extend(
        [
            "",
            "## Machine authority",
            f"Use `{schema_module}` as the authoritative loader/schema reference.",
            "",
            "## Repair contract",
            "- Edit only existing TODO YAML required to fix the diagnostic.",
            "- Preserve intent, ids, ordering, dependencies, checklist state, done values, "
            "and evidence unless the diagnostic requires a contract correction.",
            "- Never mark additional work complete.",
            "- Do not change files outside the TODO YAML set.",
            "- Do not stage, commit, reset, stash, or rewrite history.",
            "- Leave acceptance to driver reload and validation.",
        ]
    )
    return _join_parts(parts)


def prompt_requires_instruction_discovery(prompt: str) -> bool:
    """Return True when the work prompt includes generic lifecycle guidance."""
    markers = (
        "Long-running commands",
        "tool-managed background",
        "Never emit the final driver signal while a shell command is still running",
    )
    return all(marker in prompt for marker in markers)
