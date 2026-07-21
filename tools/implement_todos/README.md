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

## Quick start

From a Git project that contains a `todos/` workspace:

```bash
python -m todos_tool validate --workspace /path/to/project
python -m todos_tool status --workspace /path/to/project
python -m todos_tool run --workspace /path/to/project
python -m todos_tool run --workspace /path/to/project --todo TASK-001
python -m todos_tool resume --workspace /path/to/project
python -m todos_tool commit --workspace /path/to/project --todo TASK-001
```

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
  work_timeout_seconds: 1800
  review_timeout_seconds: 900
  auto_commit: true
  stop_on_failure: true
  model: composer-2.5   # default; set null to use Cursor default instead
items:
  - id: TASK-001
    file: items/001-feature.yaml
```

`settings.model` defaults to `composer-2.5`. Work and review sessions pass `--model` to the Cursor agent. Omit the field to keep the default, set another slug to change it, or set `null` to defer to Cursor's account default. The CLI flag `--model` overrides this value for a single run.

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
  commands:
    - pytest
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
3. Encode dependencies with `depends_on`.
4. Write concrete acceptance criteria and validation commands.
5. Leave `status: pending` and empty `result` fields.
6. Do not hand-edit `todos/runs/` — the tool owns that.

## Execution model

```text
Logical attempt
├── Work phase  (one or more Cursor sessions)
└── Review phase (fresh Cursor session, --mode ask)
```

- Default: **5** logical attempts, **2** session restarts per phase.
- Timeouts / recoverable stream failures restart the **same** phase without consuming a logical attempt.
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

A `pass` is accepted only when every acceptance criterion passes, mandatory validation passes, instruction compliance passes, no unresolved **blocking** issue exists (info/low notes are allowed), and `item_id` / `logical_attempt` match the active run.

## Streaming

Uses Cursor non-interactive streaming:

```bash
agent -p --force --trust --output-format stream-json --stream-partial-output ...
```

Flags are probed from `agent --help` at runtime. Events are normalized to categories such as `[assistant]`, `[thinking]`, `[tool:start]`, `[status]`, `[error]`. Assistant and thinking text stream as continuous blocks (thinking gets a single `[thinking]` prefix; tool lines include paths/commands). Prompt echoes (`user`) and headless approval chatter (`interaction_query`) are suppressed. Thinking is rendered only when the stream provides it. Persisted logs contain no ANSI color codes.

## Git safety

- Refuses unrelated dirty trees unless `--allow-dirty` (todos item/run metadata is ignored).
- Stages **explicit paths** only — never `git add .` / `git add -A`.
- One commit per successful item after review pass.
- Commit prefixes: `feat` / `fix` / `refactor`.
- Subjects are short, imperative, ≤72 chars, and must not mention AI/agent/Cursor/TODO/item IDs.

## Resume

`python -m todos_tool resume` reconciles `todos/runs/<id>/state.json` with Git status. It recovers from crashes during work, review, staging, commit, or final status update, and prevents duplicate commits when commit already completed.

## Controlled restructuring

A work session may write `todos/runs/<item-id>/restructure-proposal.json` to propose splits, new dependencies, or `superseded`. The orchestrator validates the proposal and rejects silent acceptance-criteria weakening or invalid graphs.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Tests use a fake Cursor executable under `tests/fixtures/fake_agent.py`. Live Cursor access is not required.

## Interrupting a run

`Ctrl+C` cancels the **todos-tool process only**. The Cursor agent is started in its own session with file-backed stdio, so interrupt detaches without sending SIGTERM/SIGINT to the agent. The tool exits with code `130`, persists `agent_pid` in `todos/runs/<id>/state.json` when the session starts, and leaves the agent running.

`status` shows a live `pid=` when recorded. Resume starts a **new** session; if a previous agent pid is still alive it warns so you can stop it manually. Dead pids are cleared. Timeouts and stream parse failures still terminate the agent process group.

## Known limitations

- Review JSON must appear in assistant text (fenced or raw object); there is no secondary success heuristic.
- Item `result.commit_sha` may be written to the item YAML after the implementation commit; that metadata-only dirty state is allowed for subsequent runs.
- Process-tree termination best-effort depends on POSIX process groups.
- Live MCP / interactive approvals are not used; runs expect `--force` / `--trust` headless operation.
- Detach-on-interrupt relies on POSIX process sessions and unreaped `Popen` children; Windows behavior may differ.
