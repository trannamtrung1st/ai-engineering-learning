# todos-tool

Generic Python CLI that executes a structured `todos/` workspace against the current project using the Cursor Agent CLI.

This tool does **not** generate the initial backlog. Another agent or user prepares `todos/` according to the schema below. The orchestrator validates, schedules, executes, reviews, commits, and resumes that work.

## Requirements

- Python 3.11+
- Git
- Cursor Agent CLI (`agent` or `cursor-agent`) authenticated via `agent login`

Install the CLI (if needed):

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

After installation, the `todos-tool` console script is available alongside `python -m todos_tool`.

## Quick start

From a Git project that contains a `todos/` workspace:

```bash
todos-tool validate --workspace /path/to/project
todos-tool status --workspace /path/to/project
todos-tool run --workspace /path/to/project
todos-tool run --workspace /path/to/project --todo TASK-001
todos-tool resume --workspace /path/to/project
todos-tool commit --workspace /path/to/project --todo TASK-001
```

Equivalent module invocations also work: `python -m todos_tool validate --workspace /path/to/project`.

To try the bundled example workspace from this repository:

```bash
cd tools/implement_todos
todos-tool validate --workspace examples
todos-tool status --workspace examples
```

Point `--workspace` at any Git checkout that contains a prepared todos directory (default name `todos`, override with `--todos-dir`).

`status` prints `auto_commit` from the manifest and a **Commit** column (`sha` prefix, `uncommitted`, or `-`).

Useful flags:

| Flag | Purpose |
|------|---------|
| `--workspace` | Git project root (default: `.`) |
| `--todos-dir` | Todos directory name (default: `todos`) |
| `--allow-dirty` | Allow unrelated uncommitted changes |
| `--no-color` | Disable colorized streaming |
| `--model` | Cursor model override (overrides `manifest.settings.model`) |
| `--agent-bin` | Path to agent binary (`TODOS_TOOL_AGENT_BIN`) |
| `--skip-probe` | Skip `agent --help` probe; use documented stream flags (`TODOS_TOOL_SKIP_PROBE`) |
| `--stop-on-failure BOOL` | Override manifest `stop_on_failure` (`true` / `false`) |
| `--auto-commit BOOL` | Override manifest `auto_commit` (`true` / `false`; default: `true`) |
| `--dry-run-prompts` | Write prompt previews without agents, validation, commits, or item/state changes |

Commit a done item that was finished without a SHA:

```bash
python -m todos_tool commit --workspace /path/to/project --todo TASK-001
```

## Todos workspace schema

```text
todos/
├── manifest.yaml
├── items/
│   ├── 001-feature.yaml
│   └── 002-fix.yaml
└── runs/                    # local artifacts (gitignored)
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
  validation_timeout_seconds: 900  # timeout for each orchestrator-run command
  auto_commit: true
  stop_on_failure: true
  parse_error_threshold: 20   # max malformed NDJSON lines before a recoverable restart
  model: composer-2.5   # default; set null to use Cursor default instead
  project_check: bash scripts/check   # required shared canonical gate for every item
items:
  - id: SETUP-001
    file: items/000-setup.yaml
  - id: TASK-001
    file: items/001-feature.yaml
```

`settings.model` defaults to `composer-2.5`. Work and review sessions pass `--model` to the Cursor agent. Omit the field to keep the default, set another slug to change it, or set `null` to defer to Cursor's account default. The CLI flag `--model` overrides this value for a single run.

`settings.parse_error_threshold` defaults to `20`. During streaming, malformed NDJSON lines increment a counter; when the threshold is reached the session fails recoverably and may restart within the same phase without consuming a logical attempt.

`settings.project_check` is **required**. The orchestrator always runs this shared command before any item-specific `validation.commands` entries (deduplicated). Use a committed, non-interactive script such as `bash scripts/check`.

`settings.max_validation_repairs_per_attempt` defaults to `2`. When authoritative validation fails, the orchestrator skips review and sends the bounded failure output back to a repair work session within the same logical attempt. After the repair budget is exhausted, the attempt is consumed.

Scheduling uses `(priority, manifest order)` with **lower priority numbers first**. Dependencies still gate readiness: an item is not executable until every `depends_on` entry is `done`.

### Item file

```yaml
version: 1
id: TASK-001
title: Add account registration
type: feature          # feature | fix | refactor
status: pending        # pending | in_progress | blocked | done | superseded
priority: 100
depends_on: []
description: |
  Implement the change using the current repository architecture.
acceptance_criteria:
  - Registration endpoint is implemented.
validation:
  commands: []   # optional item-specific gates beyond manifest.settings.project_check
context:
  files:
    - docs/requirements.md
result:
  completed_at: null
  commit_sha: null
  summary: null
```

See [`examples/todos/`](examples/todos/) for a minimal valid workspace.

### Preparing a workspace (for other agents)

1. Create `todos/manifest.yaml` and `todos/items/*.yaml`.
2. Use unique `id` values; list every item in the manifest.
3. Add a first setup item (convention: id prefix `SETUP-`) that creates or reuses a canonical project check and sets `manifest.settings.project_check`.
4. Make implementation items depend on the setup item when the shared check is required.
5. Encode dependencies with `depends_on`.
6. Write concrete acceptance criteria. Use item `validation.commands` only for extra gates beyond `project_check`.
7. Leave `status: pending` and empty `result` fields.
8. Do not hand-edit `todos/runs/` — the tool owns that.

## Execution model

```text
Logical attempt
├── Work phase  (one or more Cursor sessions; targeted local checks only)
├── Validation gate  (orchestrator runs project_check + item commands once)
│   └── on failure: repair work loop (bounded, same attempt)
└── Review phase (fresh Cursor session, --mode ask; read-only, no reruns)
```

- Default: **5** logical attempts, **2** session restarts per phase, **2** validation repairs per attempt.
- Timeouts / recoverable stream failures restart the **same** phase without consuming a logical attempt.
- The orchestrator runs `project_check` plus any item-specific validation commands sequentially outside Cursor. Work agents must not run the full authoritative suite; reviewers must not rerun it.
- Failed authoritative validation skips review and returns repair feedback to the implementer within the same logical attempt.
- A failed or invalid independent review consumes one logical attempt.
- Missing Cursor CLI or auth failures block immediately.

## Rules and skills

Every work and review prompt requires discovery of applicable instructions:

- `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`
- `.cursor/rules/`
- `.cursor/skills/**/SKILL.md`

Rules are mandatory when applicable. Skills are selected only when relevant.

## Review contract

Success is determined only by a validated JSON decision (`schema_version: 1`) with:

- `decision`: `pass` | `fail` | `blocked`
- `recommended_next_action`: `mark_done` | `retry` | `block`
- Per-criterion results, validation results, and instruction compliance

A `pass` is accepted only when every acceptance criterion is reported **exactly** (normalized match, no substitutions or duplicates), every resolved validation command matches the orchestrator's authoritative command/exit-code result and passes, instruction compliance passes, no unresolved **blocking** issue exists (info/low notes are allowed), and `item_id` / `logical_attempt` match the active run.

Resolved validation commands are always `settings.project_check` followed by item-specific commands, deduplicated. Review passes must copy the orchestrator's authoritative command results exactly; item YAML alone is never sufficient.

## Streaming

Uses Cursor non-interactive streaming:

```bash
agent -p --force --trust --output-format stream-json --stream-partial-output ...
```

Flags are probed from `agent --help` at runtime. Events are normalized to categories such as `[assistant]`, `[thinking]`, `[tool:start]`, `[status]`, `[error]`. Assistant and thinking text stream as continuous blocks (thinking gets a single `[thinking]` prefix; tool lines include paths/commands). Prompt echoes (`user`) and headless approval chatter (`interaction_query`) are suppressed. Thinking is rendered only when the stream provides it. Persisted logs contain no ANSI color codes.

## Git safety

- Refuses unrelated dirty trees unless `--allow-dirty` (todos item/run metadata is ignored).
- With `--allow-dirty`, files that were already dirty before the run are **immutable**: if the agent modifies them, the run fails instead of silently omitting them from the commit.
- **Never** allows unrelated **staged** content, even with `--allow-dirty`; unstage foreign index entries before running.
- Stages **explicit paths** only — never `git add .` / `git add -A`.
- Verifies the staged set exactly matches approved paths for each commit.
- One commit per successful item after review pass.
- Backfill `commit --todo` applies the same staged-content policy; only paths attributable to the done item (plus its item YAML) may be dirty.
- Commit prefixes: `feat` / `fix` / `refactor`.
- Subjects are short, imperative, ≤72 chars, and must not mention AI/agent/Cursor/TODO/item IDs.
- Git path parsing uses NUL-delimited porcelain/name-only output so paths with spaces or unusual characters are handled safely.

## Run vs resume

- `run` refuses to start when any item is already `in_progress` or has non-idle persisted run state. Use `resume` instead.
- `resume` refuses while a Cursor agent PID from `state.json` is still alive (for example if termination failed); stop that process first.
- Outcomes are recorded explicitly in `RunReport`: `failed` for terminal failures, `retryable` for errors that leave the item `in_progress`, and `blocked` for policy/review exhaustion. The CLI exits `1` when any of these lists is non-empty.
- `stop_on_failure: true` stops batch runs after the first failed, retryable, or blocked item. A retryable item always stops the batch regardless of this setting to preserve the single-active-item invariant.

## Prompt-only dry run

`run --dry-run-prompts` and `resume --dry-run-prompts` write work/review previews under `todos/runs/<id>/dry-run/`. They do not resolve or start Cursor, run validation, commit, or modify item YAML/state. Resume previews use the persisted logical attempt, summary, diff, and cached authoritative validation when available, and enforce the same dirty-tree and live-agent preflight as a real resume. In an unconstrained batch, previews cover only items that are ready in the current dependency state.

## Prompt delivery

Work and review sessions write the full prompt to `todos/runs/<id>/attempts/<NN>/…-prompt-<session>.md`. The Cursor agent receives a short bootstrap prompt pointing at that file, avoiding OS argument-size limits on large diffs.

## Resume

`python -m todos_tool resume` reconciles `todos/runs/<id>/state.json` with Git status. It recovers from crashes during work, review, staging, commit, or final status update, prevents duplicate commits when commit already completed (persisted SHAs are verified in Git), and preserves monotonic session numbers so artifacts are not overwritten.

## Controlled restructuring

A work session may write `todos/runs/<item-id>/restructure-proposal.json` to propose splits, new dependencies, or `superseded`. The orchestrator validates the proposal and rejects silent acceptance-criteria weakening or invalid graphs.

## Tests

```bash
pip install -e ".[dev]"
pytest
python -m todos_tool validate --workspace examples
python -m build
pip install dist/todos_tool-*.whl
todos-tool --version
```

Tests use a fake Cursor executable under `tests/fixtures/fake_agent.py`. Live Cursor access is not required for `validate`, `status`, or Git-only `commit` paths — the Cursor CLI is resolved lazily when a work/review session starts.

An opt-in smoke test verifies that a live authenticated Cursor agent follows the persisted prompt bootstrap:

```bash
TODOS_TOOL_RUN_LIVE_SMOKE=1 pytest tests/live/test_cursor_prompt_bootstrap.py
```

## Interrupting a run

`Ctrl+C` cancels the tool and **terminates the Cursor agent** (SIGTERM, then SIGKILL if needed). The tool exits with code `130`, clears `agent_pid` in persisted state, and saves partial progress where applicable. While a session is active, `agent_pid` is recorded in `todos/runs/<id>/state.json` for resume safety checks.

`status` shows a live `pid=` when recorded. Resume **refuses** while that pid is still alive; stop the process manually, then resume. Dead pids are cleared automatically. Timeouts and stream parse failures still terminate the agent process group.

## Known limitations

- Review JSON must appear in assistant text (fenced or raw object); there is no secondary success heuristic.
- Item `result.commit_sha` may be written to the item YAML after the implementation commit; that metadata-only dirty state is allowed for subsequent runs.
- Process-tree termination best-effort depends on POSIX process groups.
- Live MCP / interactive approvals are not used; runs expect `--force` / `--trust` headless operation.
- Detach-on-interrupt relies on POSIX process sessions and unreaped `Popen` children; Windows behavior may differ.
