# todos-tool

Standalone Python CLI that executes a structured TODO workspace in **any Git repository** using the Cursor Agent CLI.

The tool is self-contained (stdlib + PyYAML only at runtime). It does not import project-specific runtimes or assume one repository's docs, test commands, or directory layout. Repository context comes from the TODO manifest, an optional repository profile (`.implement-todos.yaml`), and explicit `--context-file` additions.

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

After installation: `todos-tool` or `python -m todos_tool`.

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
| `--project-config` | Repository profile YAML (default: `.implement-todos.yaml` when present) |
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

Inspection commands (`validate`, `status`) never repair or modify TODO YAML.

## Run config

Optional YAML run config for `run` and `resume` (see [`examples/run.config.yaml`](examples/run.config.yaml)):

```bash
todos-tool run --config ./run.config.yaml
todos-tool run --config ./run.config.yaml --todo TASK-001
```

CLI flags override config values. Paths resolve relative to `workspace` (or the config file directory when `workspace` is `.`).

Supported keys include `workspace`, `todos_dir`, `model`, `auto_commit`, `stop_on_failure`, `skip_commit`, `project_config`, `context_files`, `commit_hint`, `commit_hint_file`, `evidence_mode`, `max_identical_evidence_failures`, and `evidence_batch_timeout_seconds`. Use either `commit_hint` or `commit_hint_file`, not both.

When no commit hint is supplied, the tool uses a built-in default requiring `agent:` plus a conventional type (`feat:`, `fix:`, or `refactor:`) and a concise subject.

## Model selection

- **Default:** `composer-2.5` (`DEFAULT_CURSOR_MODEL` in `models.py`)
- **Override:** `--model <slug>` or env var `TODOS_TOOL_MODEL`
- **Manifest:** `settings.model` in `manifest.yaml` (omit for default; set `null` to use Cursor's default)
- **Precedence:** CLI `--model` → `TODOS_TOOL_MODEL` → manifest `settings.model` → package default

Resolution lives in [`model_config.py`](src/todos_tool/model_config.py) and is applied when building the Cursor client in the orchestrator.

## Repository profile

Optional `.implement-todos.yaml` at the repository root:

```yaml
schema_version: 1

context:
  files:
    - path: AGENTS.md
      required: false
    - path: CONTRIBUTING.md
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
```

Precedence: CLI overrides → profile → neutral defaults. Required missing context files fail before Cursor sessions. Optional missing files are skipped.

See [`examples/.implement-todos.yaml`](examples/.implement-todos.yaml) for a neutral example.

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
items:
  - id: TASK-001
    file: items/001-feature.yaml
```

`settings.project_check` is optional. When present, the orchestrator runs it plus item-specific `validation.commands` (deduplicated). Profile `evidence.required_commands` add repository-level gates.

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
checklist: []          # optional {id, text, done} entries
validation:
  commands: []
evidence:
  commands: []         # optional mapping entries: {command, cwd?, timeout_seconds?}
context:
  files: []
result:
  completed_at: null
  commit_sha: null
  summary: null
```

See [`examples/todos/`](examples/todos/) for sample items.

## Execution model

```text
Logical attempt
├── Work phase (Cursor; targeted local checks; tool-managed background commands)
├── Completion-evidence gate (captured shell logs or driver execution)
│   └── on failure: bounded repair work loop (same attempt)
├── Validation gate (orchestrator runs configured commands)
│   └── on failure: bounded repair work loop (same attempt)
└── Review phase (Cursor ask mode; read-only; no shell commands)
```

Only observed shell execution counts for item `evidence.commands`. YAML `result` text never proves execution. In **captured** mode (default), implement sessions must run each declared command literally and set the shell tool working-directory field for `cwd`. In **driver** mode, the orchestrator executes evidence commands once and implementers must not duplicate them.

Malformed TODO YAML may be repaired automatically during `run` / `resume` (bounded attempts). Repair succeeds only when the driver reloads and validates the set; agent claims are never acceptance.

## Prompts and context

Work, review, continuation, and repair prompts include only supplied context:

- Manifest authority, hard rules, stop conditions, out-of-scope text
- Item contract refs, checklist state, context files
- Profile/CLI context files and instructions

Empty sections are omitted. There are no built-in hard-coded instruction paths.

Implementation prompts require tool-managed background execution for long commands, forbid shell `&` / `nohup`, and require all background jobs to resolve before the session ends.

## Git behavior

**Whole-worktree ownership:** by starting the driver, you authorize normal finalization to commit the complete current worktree state.

- Dirty, pre-staged, and manually committed work are accepted by default.
- After review pass, the review session proposes `proposed_commit_message` using the configured commit hint (or the built-in default). Python then runs `git add -A` and commits with that exact subject.
- Legacy resume/manual commit paths without a stored proposal still use `agent: finalize worktree`.
- `--skip-commit` performs no staging or commit.
- `baseline_head` is review/evidence context, not a file-ownership boundary.
- Provenance is recorded as `driver`, `external` (clean tree with advanced HEAD), or `skipped`.
- The tool never resets, stashes, amends, or rewrites user commits.

## Review contract

Success requires a validated JSON decision (`schema_version: 1`) with exact acceptance-criterion coverage, authoritative validation results copied from the orchestrator, authoritative completion-evidence results copied when `evidence.commands` is configured, instruction compliance, no unresolved blocking issues, and on pass a non-empty `proposed_commit_message` for the orchestrator commit step. Review sessions do not rerun validation or evidence commands.

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

- Review JSON must appear in assistant text; there is no secondary success heuristic.
- Process-tree termination is best-effort and depends on POSIX process groups.
- Live MCP / interactive approvals are not used; runs expect headless `--force` / `--trust` operation.
