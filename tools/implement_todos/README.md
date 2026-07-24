# todos-tool

Standalone Python CLI that executes a structured TODO workspace in **any Git repository** using the Cursor Agent CLI.

The tool is self-contained at runtime (`PyYAML` + `notify-py`). It does not import project-specific runtimes or assume one repository's docs, test commands, or directory layout. Repository context comes from the TODO manifest, the optional run config (`--config`), and explicit `--context-file` additions.

This tool does **not** generate the initial backlog. Another agent or user prepares the TODO set according to the schema below. The orchestrator validates, schedules, executes, reviews, finalizes Git state, and resumes work.

## Requirements

- Python 3.11+
- Git
- Cursor Agent CLI (`agent` or `cursor-agent`) authenticated via `agent login`

```bash
curl https://cursor.com/install -fsS | bash
agent login
```

## Installation

```bash
cd tools/implement_todos
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

After installation: `todos-tool`, `todos-review-tool`, or `python -m todos_tool`.

## Quick start

From a Git project with a prepared TODO workspace (default directory name `todos`):

```bash
todos-tool validate --workspace /path/to/project
todos-tool status --workspace /path/to/project
todos-tool run --workspace /path/to/project
todos-tool run --workspace /path/to/project --todo TASK-001
todos-tool resume --workspace /path/to/project
```

Bundled example:

```bash
cd tools/implement_todos
todos-tool validate --workspace examples
todos-tool status --workspace examples
```

## CLI flags

| Flag | Purpose |
|------|---------|
| `--workspace` | Git project root (default: `.`) |
| `--todos-dir` | TODO workspace directory (default: `todos`) |
| `--config`, `-c` | Optional YAML run config (CLI flags override) |
| `--commit-hint` | Markdown guidance for review commit subjects |
| `--commit-hint-file` | Markdown file with commit-subject guidance |
| `--context-file` | Additional context file, repeatable |
| `--skip-commit` | Finalize without `git add` / commit |
| `--no-auto-repair-yaml` | Fail on malformed TODO YAML instead of bounded repair |
| `--max-yaml-repair-attempts N` | Repair budget (default: `2`; `0` = fail-fast) |
| `--dry-run` | Report that YAML repair would be required (no Cursor) |
| `--dry-run-prompts` | Write prompt previews only |
| `--evidence-mode` | Completion-evidence mode: `captured` (default) or `driver` |
| `--max-identical-evidence-failures N` | Stop after N identical evidence failures (default: `3`) |
| `--evidence-batch-timeout-seconds N` | Optional global timeout for driver-mode evidence batches |
| `--no-color` | Plain-text console output |
| `--model` | Cursor model override (default: `composer-2.5`; env: `TODOS_TOOL_MODEL`) |
| `--agent-bin` | Agent binary path (`TODOS_TOOL_AGENT_BIN`) |
| `--skip-probe` | Skip `agent --help` stream-flag probe |
| `--stop-on-failure BOOL` | Override manifest `stop_on_failure` |
| `--auto-commit BOOL` | Override manifest `auto_commit` |

| `--force-reset` | Clear run state and reset items to pending before running |
| `--notify` / `--no-notify` | Enable or disable desktop notifications (default: on for desktop sessions) |

Inspection commands (`validate`, `status`) never repair or modify TODO YAML.

## Desktop notifications

Long-running `run`, `resume`, and `commit` commands can emit native desktop notifications when a terminal outcome is reached (run finished, interrupted, failed, or commit succeeded/failed).

- **Default:** enabled on desktop sessions; disabled when `CI=true` or on headless Linux (no display/D-Bus session)
- **CLI:** `--notify` / `--no-notify`
- **Env:** `TODOS_TOOL_NOTIFY=true|false`
- **Config:** `notify: true|false` in run YAML

Per-item notifications during multi-item `run` / `resume` are opt-in:

- **Config:** `notify_per_item: true|false` in run YAML (default: `false`)
- **CLI:** `--notify-per-item` / `--no-notify-per-item`
- **Env:** `TODOS_TOOL_NOTIFY_PER_ITEM=true|false`

When `notify_per_item` is enabled, each successfully completed item emits a desktop notification with the item id, title, and commit SHA when available. The run-level summary notification still fires when the command exits. Per-item notifications require the master `notify` switch to be on.

Notifications are fail-soft: backend errors never change exit codes. Phase-level progress (work, review, evidence, validation) is not notified to avoid alert fatigue.

## Run config

Optional YAML run config for `run` and `resume` (see [`examples/run.config.yaml`](examples/run.config.yaml)):

```bash
todos-tool run --config ./run.config.yaml
todos-tool run --config ./run.config.yaml --todo TASK-001
```

CLI flags override config values. Paths resolve relative to `workspace` (or the config file directory when `workspace` is `.`).

Supported keys include `workspace`, `todos_dir`, `model`, `auto_commit`, `stop_on_failure`, `skip_commit`, `context`, `authority`, `evidence`, `git`, `agent_context`, `context_files`, `commit_hint`, `commit_hint_file`, `evidence_mode`, `max_identical_evidence_failures`, `evidence_batch_timeout_seconds`, `notify`, and `notify_per_item`. Use either `commit_hint` or `commit_hint_file`, not both.

When no `--config` is supplied, repository policy defaults to neutral values. `.implement-todos.yaml` is no longer supported.

When no commit hint is supplied, the tool uses a built-in default requiring `agent:` plus a conventional type (`feat:`, `fix:`, or `refactor:`) and a concise subject.

## Repository policy (run config)

Repository-level context, evidence gates, git prefix, and agent skills/rules live in the run config:

```yaml
context:
  files:
    - path: AGENTS.md
      required: false
  instructions:
    - Follow the repository's existing architecture and naming.

authority:
  forbidden_path_globs: []

evidence:
  required_commands:
    - pytest
  forbidden_command_patterns: []

git:
  commit_prefix: "agent:"

agent_context:
  default:
    skills:
      - .cursor/skills/shared/SKILL.md
    rules:
      - .cursor/rules/shared.mdc
    model: composer-2.5
  implement:
    skills:
      - .cursor/skills/implement/SKILL.md
    model: gpt-5.6-sol-high
  review:
    skills:
      - .cursor/skills/review/SKILL.md
```

CLI `--context-file` entries merge additively with `context.files`. Required missing context files fail before Cursor sessions. Optional missing files are skipped.

See [`examples/run.config.yaml`](examples/run.config.yaml) for a working example.

## Model selection

- **Default:** `composer-2.5` (`DEFAULT_CURSOR_MODEL` in `models.py`)
- **Override:** `--model <slug>` or env var `TODOS_TOOL_MODEL`
- **Manifest:** `settings.model` in `manifest.yaml` (omit for default; set `null` to use Cursor's default)
- **Precedence:** CLI `--model` → `TODOS_TOOL_MODEL` → manifest `settings.model` → package default

Resolution lives in [`model_config.py`](src/todos_tool/model_config.py) and is applied when building the Cursor client in the orchestrator.

## TODO workspace schema

```text
todos/                       # location is configurable via --todos-dir
├── manifest.yaml
├── items/
│   └── TASK-001.yaml
└── runs/                    # local artifacts (typically gitignored)
    └── <item-id>/
        ├── state.json
        └── attempts/
```

### manifest.yaml

```yaml
version: 1
settings:
  max_attempts: 5
  max_session_restarts_per_phase: 2
  max_validation_repairs_per_attempt: 2
  work_timeout_seconds: 1800
  review_timeout_seconds: 900
  validation_timeout_seconds: 900
  auto_commit: true
  stop_on_failure: true
  parse_error_threshold: 20
  model: composer-2.5
  project_check: pytest   # optional legacy shared gate
authority: []               # optional manifest authority references
hard_rules: []              # optional free-form rules
stop_conditions: []
out_of_scope: []
agent_context:          # optional manifest-level additions
  implement:
    rules:
      - .cursor/rules/manifest-implement.mdc
items:
  - id: TASK-001
    file: items/001-feature.yaml
```

`settings.project_check` is optional. When present, the orchestrator runs it plus item-specific `validation.commands` (deduplicated). Run-config `evidence.required_commands` add repository-level gates.

### Agent context merge order

Effective skills and rules for each phase merge additively (deduplicated by path) in this order:

1. Run config `default`, then phase (`implement` or `review`)
2. Manifest `default`, then phase
3. Item `default`, then phase

Optional `model` entries use the same layer order; the most specific configured model wins. When no phase model is configured, the run uses the normal model precedence: CLI `--model` → `TODOS_TOOL_MODEL` → manifest `settings.model` → package default.

Configured paths must exist as files under the workspace. Work prompts receive the implement set; review prompts receive the review set. When `agent_context` is omitted everywhere, no agent-context section is added to prompts.

### Item file

```yaml
version: 1
id: TASK-001
title: Add account registration
type: feature          # feature | fix | refactor
status: pending
priority: 100
depends_on: []
description: |
  Implement the requested change.
acceptance_criteria:
  - Registration endpoint is implemented.
contract_refs: []      # optional authority references
checklist: []          # optional {id, text, done} entries; agent-owned work plan
validation:
  commands: []
evidence:
  commands: []         # optional mapping entries: {command, cwd?, timeout_seconds?}
context:
  files: []
# allow_empty_commit defaults to true; set false to require a tracked commit
agent_context:          # optional item-level additions
  review:
    rules:
      - .cursor/rules/item-review.mdc
result:
  completed_at: null
  commit_sha: null
  summary: null
```

See [`examples/todos/`](examples/todos/) for sample items.

### Checklist work plan

When present, `checklist` is the agent-owned execution plan for that item. Each entry uses `{id, text, done}` where `id` must be unique within the item.

- Work agents cover open steps or reshape the checklist as reality changes.
- In-item edits are allowed on the current item only: reorder, update `text`, add, remove obsolete steps, toggle `done`.
- Removals should be justified in the work summary.
- Cross-item transfers use `checklist_moves` in `todos/runs/<item-id>/restructure-proposal.json`; do not edit other item files directly.
- Item `status` remains orchestrator-owned; checklist progress does not replace acceptance criteria.

Example restructure proposal with checklist transfer:

```json
{
  "schema_version": 1,
  "item_id": "TASK-001",
  "supersede": false,
  "new_items": [],
  "dependency_updates": {},
  "checklist_moves": [
    {"id": "ck-tests", "to_item_id": "TASK-002"}
  ],
  "notes": "Tests belong with the fix item."
}
```

Review applies soft pressure: open checklist entries without justification should fail `instruction_compliance`. Acceptance criteria, evidence, and validation remain the hard gates.

## Execution model

```text
Logical attempt
├── Work phase (Cursor; targeted local checks; tool-managed background commands)
├── Completion-evidence gate (captured shell logs or driver execution)
│   └── on failure: bounded repair work loop (same attempt)
├── Validation gate (orchestrator runs configured commands)
│   └── on failure: bounded repair work loop (same attempt)
└── Review phase (Cursor; read-only; submit via todos-review-tool only)
```

Only observed shell execution counts for item `evidence.commands`. YAML `result` text never proves execution. In **captured** mode (default), implement sessions must run each declared command literally and set the shell tool working-directory field for `cwd`. In **driver** mode, the orchestrator executes evidence commands once and implementers must not duplicate them.

Malformed TODO YAML may be repaired automatically during `run` / `resume` (bounded attempts). Repair succeeds only when the driver reloads and validates the set; agent claims are never acceptance.

## Prompts and context

Work, review, continuation, and repair prompts include only supplied context:

- Manifest authority, hard rules, stop conditions, out-of-scope text
- Item contract refs, checklist state and work-plan rules, context files
- Run-config context files and instructions
- Phase-specific agent skills and rules (when configured)

Empty sections are omitted. There are no built-in hard-coded instruction paths.

Implementation prompts require tool-managed background execution for long commands, forbid shell `&` / `nohup`, and require all background jobs to resolve before the session ends.

## Git behavior

**Whole-worktree ownership:** by starting the driver, you authorize normal finalization to commit the complete current worktree state.

- Dirty, pre-staged, and manually committed work are accepted by default.
- After review pass, the review session proposes `proposed_commit_message` using the configured commit hint (or the built-in default). Python then runs `git add -A` and commits with that exact subject.
- Legacy resume/manual commit paths without a stored proposal still use `agent: finalize worktree`.
- `--skip-commit` performs no staging or commit.
- `baseline_head` is review/evidence context, not a file-ownership boundary.
- Provenance is recorded as `driver`, `external` (clean tree with advanced HEAD), `skipped`, or `unchanged` (no trackable source changes and unchanged HEAD; default item behavior). Gitignored deliverables and todos workspace metadata alone do not block `unchanged` finalize. Set `allow_empty_commit: false` on an item to require a tracked commit.
- The tool never resets, stashes, amends, or rewrites user commits.

## Review contract

Success requires a validated review submission artifact (`schema_version: 1`) with exact acceptance-criterion coverage, authoritative validation results copied from the orchestrator, authoritative completion-evidence results copied when `evidence.commands` is configured, instruction compliance (including checklist coverage when the item has open steps without justification), no unresolved blocking issues, and on pass a non-empty `proposed_commit_message` when there are trackable changes to commit (or when the item sets `allow_empty_commit: false`). Review sessions submit decisions through `todos-review-tool`; assistant chat is not parsed. Review sessions do not rerun validation or evidence commands.

Missing or invalid review artifacts restart only the review session. After `max_session_restarts_per_phase` is exhausted, the item is blocked with the artifact diagnostic instead of silently consuming another work attempt.

## Streaming and transport

Cursor sessions use stream-json output with incremental parsing, optional color console rendering, timeout/cancellation with process-tree cleanup, and shell-command evidence extraction from stream events.

Full prompts are written to `todos/runs/<id>/attempts/<NN>/…-prompt-<session>.md`; the agent receives a short bootstrap pointing at that file.

## Resume

`resume` reconciles persisted `state.json` with on-disk Git and TODO YAML, then continues the same scheduling loop as `run` (ready items in priority order). It prevents duplicate driver commits, accepts manual commits between baseline and HEAD, retries persisted commit failures, and refuses while a live `agent_pid` is recorded.

Use `run --force-reset` or `resume --force-reset` to clear persisted run state and reset all items to `pending` before starting (scoped to `--todo` on `run` when set). Checklist `done` flags in item YAML are preserved.

## Tests

```bash
pip install -e ".[dev]"
pytest
python -m todos_tool validate --workspace examples
PYTHONPATH=src python -m todos_tool --help
```

Tests use `tests/fixtures/fake_agent.py` — no live Cursor required for the main suite.

Opt-in live smoke:

```bash
TODOS_TOOL_RUN_LIVE_SMOKE=1 pytest tests/live/test_cursor_prompt_bootstrap.py
```

## Interrupting a run

`Ctrl+C` terminates the Cursor agent process tree and exits `130`. Partial progress is persisted where applicable.

## Known limitations

- Review decisions must be submitted through `todos-review-tool`; assistant chat is not parsed.
- Process-tree termination is best-effort and depends on POSIX process groups.
- Live MCP / interactive approvals are not used; runs expect headless `--force` / `--trust` operation.
