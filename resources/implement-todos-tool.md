# Implement a Generic TODO Execution Tool

Implement a reusable Python CLI that executes a structured `todos/` workspace against the current project using Cursor Agent CLI.

The tool must not generate the initial backlog itself. Another agent or user prepares the `todos/` folder according to the documented schema. This tool validates, schedules, executes, reviews, commits, and resumes that work using the surrounding repository as project context.

## 1. Goals

The tool must:

1. Load and validate a `todos/` workspace.
2. Execute items in dependency-safe order.
3. Use Cursor Agent CLI to implement each item.
4. Run a separate independent review session.
5. Retry failed work up to five logical attempts.
6. Restart interrupted Cursor sessions without incorrectly consuming an attempt.
7. Follow applicable repository rules and `.cursor` skills.
8. Stream structured Cursor output to a readable colorized console.
9. Persist enough state to resume after interruption.
10. Commit each successfully completed item with a concise developer-style commit message.

The Python orchestrator owns scheduling, state transitions, review acceptance, staging, commits, and completion status.

Cursor sessions must not commit or mark items complete.

---

## 2. Generic TODO Workspace

Use this format:

```text
todos/
├── manifest.yaml
├── items/
│   ├── 001-feature.yaml
│   ├── 002-fix.yaml
│   └── 003-refactor.yaml
└── runs/
    └── <item-id>/
        ├── state.json
        └── attempts/
```

`todos/runs/` contains local execution artifacts and should normally be ignored by Git.

### `manifest.yaml`

```yaml
version: 1

settings:
  max_attempts: 5
  max_session_restarts_per_phase: 2
  work_timeout_seconds: 1800
  review_timeout_seconds: 900
  auto_commit: true
  stop_on_failure: true

items:
  - id: TASK-001
    file: items/001-feature.yaml

  - id: TASK-002
    file: items/002-fix.yaml
```

### Item schema

```yaml
version: 1

id: TASK-001
title: Add account registration
type: feature
status: pending
priority: 100

depends_on: []

description: |
  Implement account registration using the current repository architecture.

acceptance_criteria:
  - Registration endpoint is implemented.
  - Input validation is present.
  - Automated tests cover success and failure cases.

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

Supported types:

```text
feature
fix
refactor
```

Supported statuses:

```text
pending
in_progress
blocked
done
superseded
```

Use typed models and return actionable validation errors.

Document this schema clearly so another agent can generate a valid `todos/` workspace for any project.

---

## 3. CLI

Implement:

```bash
python -m todos_tool validate
python -m todos_tool status
python -m todos_tool run
python -m todos_tool run --todo TASK-001
python -m todos_tool resume
```

Behavior:

* `validate`: validate schemas, files, dependencies, cycles, and duplicate IDs.
* `status`: show item readiness and active execution state.
* `run`: execute ready items in dependency-safe manifest order.
* `run --todo`: execute one eligible item.
* `resume`: recover from persisted state and actual Git state.

---

## 4. Scheduling

An item is executable when:

1. Its status is `pending`, or it is a resumable `in_progress` item.
2. All dependencies are `done`.
3. It is not `blocked` or `superseded`.

Use manifest order as the primary ordering and priority as a secondary signal.

Detect missing dependencies, cycles, duplicate IDs, missing files, and invalid active state.

---

## 5. Execution Model

Keep these concepts separate:

```text
Logical attempt
├── Work phase
│   └── One or more Cursor sessions
└── Review phase
    └── One or more Cursor sessions
```

A logical attempt represents one substantive implementation and review cycle.

A timeout, process crash, or recoverable stream failure restarts the current phase and does not immediately consume a logical attempt.

Default behavior:

```text
5 logical attempts
2 session restarts per phase
```

A failed independent review consumes one logical attempt.

### Work phase

The work session receives:

* Item description
* Acceptance criteria
* Relevant context files
* Required validation commands
* Current attempt number
* Previous review feedback
* Continuation context when restarting

It must:

1. Inspect the current repository.
2. Inspect applicable project instructions, rules, and skills.
3. Implement the requested change.
4. Run targeted validation.
5. Leave the working tree ready for review.
6. Return a concise summary.

It must not commit or mark the item complete.

### Review phase

Run review in a fresh Cursor session.

The reviewer must independently inspect:

* The item and acceptance criteria
* Repository instructions
* Applicable rules and skills
* Current Git diff
* Work summary
* Validation results

The reviewer should remain read-only where practical and return a structured decision.

---

## 6. Rules and Skills

Every work and review session must inspect applicable instructions, including where present:

```text
AGENTS.md
CLAUDE.md
CONTRIBUTING.md
README.md
.cursor/rules/
.cursor/skills/**/SKILL.md
```

Rules are mandatory when applicable.

Skills are selected task-specific workflows.

The session must:

1. Identify applicable global and scoped rules.
2. Select relevant skills only.
3. Follow required workflows and validation.
4. Re-check scoped rules when modifying new directories or file types.
5. Report instruction conflicts.

Every generated Cursor prompt must explicitly require this discovery process.

---

## 7. Review Decision

Do not determine success by searching normal text for words such as `done` or `passed`.

Require a validated JSON decision:

```json
{
  "schema_version": 1,
  "item_id": "TASK-001",
  "logical_attempt": 1,
  "decision": "pass",
  "summary": "The implementation satisfies the acceptance criteria.",
  "acceptance_criteria": [
    {
      "criterion": "Registration endpoint is implemented.",
      "passed": true,
      "evidence": "Implemented and covered by tests."
    }
  ],
  "validation": [
    {
      "command": "pytest",
      "passed": true,
      "exit_code": 0,
      "summary": "128 tests passed."
    }
  ],
  "instruction_compliance": {
    "passed": true,
    "violations": []
  },
  "issues": [],
  "recommended_next_action": "mark_done"
}
```

Allowed decisions:

```text
pass
fail
blocked
```

Allowed actions:

```text
mark_done
retry
block
```

A pass is valid only when:

* Every acceptance criterion passes.
* Mandatory validation passes.
* Instruction compliance passes.
* No unresolved blocking issue exists.
* The item ID and logical attempt match the active run.

Malformed, contradictory, missing, or stale review output must not complete an item.

---

## 8. Cursor Session Recovery

Use `asyncio.create_subprocess_exec`, never `shell=True`.

When a Cursor session times out or fails recoverably:

1. Terminate it gracefully, then force-kill if needed.
2. Preserve received output.
3. Inspect current Git status and diff.
4. Build bounded continuation context.
5. Start a replacement session for the same phase and logical attempt.

Continuation must include:

* Original item
* Acceptance criteria
* Current attempt and phase
* Current Git status and diff summary
* Files already changed
* Known validation results
* Previous session summary
* Failure reason
* Instruction to inspect and preserve valid existing work

Do not paste unlimited raw output into the next prompt.

Environment-wide failures, such as missing Cursor CLI or unavailable authentication, should block immediately rather than consume every attempt.

---

## 9. Structured Streaming

Use Cursor CLI’s actual supported non-interactive streaming JSON mode.

Inspect the installed Cursor version and help output instead of hardcoding undocumented flags.

Read stdout and stderr concurrently.

For stdout:

1. Decode UTF-8 incrementally.
2. Buffer incomplete data.
3. Split on complete newline boundaries.
4. Parse each NDJSON line independently.
5. Preserve event order.
6. Persist original events.
7. Normalize events for rendering.

Malformed lines must be recorded and reported without immediately crashing the whole run. Fail the session after a configurable parse-error threshold.

Unknown event types must be preserved and rendered generically.

Normalize events into categories such as:

```text
[assistant]
[thinking]
[tool:start]
[tool:output]
[tool:end]
[status]
[warning]
[error]
[unknown]
```

Do not fabricate thinking events.

Use `rich` or equivalent for colorized output and support `--no-color`.

Persisted logs must not contain terminal color codes.

---

## 10. Persistence and Resume

Persist state atomically after meaningful transitions, including:

```text
attempt_started
work_session_started
work_session_restarted
work_phase_ready
review_session_started
review_session_restarted
review_passed
review_failed
commit_started
commit_completed
commit_failed
item_done
item_blocked
```

State must distinguish:

* Logical attempt
* Phase
* Session number
* Session restart count
* Review result
* Commit state

On resume, inspect both persisted state and actual Git state.

Support recovery after crashes during work, review, staging, commit, or final state update.

Prevent stale session output and duplicate commits.

---

## 11. Controlled Item Restructuring

Cursor may discover that an item should be split, deferred, reordered, or replaced.

Allow it to propose:

* New item files
* New dependencies
* Follow-up work
* Item splitting
* `superseded` status

The orchestrator must validate all changes.

Do not allow silent deletion, hidden weakening of acceptance criteria, invalid dependency graphs, or restructuring used to falsely complete unfinished work.

---

## 12. Git and Commits

Refuse to start with unrelated uncommitted changes by default.

Provide an explicit `--allow-dirty` override, but never stage pre-existing unrelated work.

Stage explicit paths rather than using broad commands such as:

```bash
git add .
git add -A
```

Create exactly one commit after review and final validation pass.

Map item type to prefix:

```text
feature  -> feat
fix      -> fix
refactor -> refactor
```

Commit subjects must:

* Be short and concise
* Use imperative mood
* Describe the actual repository change
* Prefer 72 characters or fewer
* Match the verified staged diff
* Avoid ending punctuation

Examples:

```text
feat: add account registration
fix: handle incomplete json events
refactor: separate attempts from sessions
```

Do not mention:

```text
AI
agent
Cursor
TODO
item ID
backlog
review
attempt
retry
generation process
automation process
```

Generate the subject primarily from the staged diff, then acceptance criteria, then the item title.

Do not mark an item `done` until the commit succeeds.

---

## 13. Suggested Modules

Use a structure similar to:

```text
src/todos_tool/
├── cli.py
├── models.py
├── manifest.py
├── scheduler.py
├── orchestrator.py
├── cursor_client.py
├── stream_parser.py
├── event_normalizer.py
├── console_renderer.py
├── prompts.py
├── reviewer.py
├── continuation.py
├── persistence.py
├── git_service.py
├── commit_message.py
└── errors.py
```

Keep process execution, stream parsing, orchestration, review validation, persistence, and Git logic separate.

---

## 14. Tests

Add unit and integration tests covering:

* Schema validation
* Dependency ordering and cycle detection
* Logical attempts versus session restarts
* Work and review lifecycle
* Timeout and process recovery
* Split JSON and split UTF-8 stream data
* Malformed and unknown events
* Review decision validation
* Rules and skills prompt requirements
* Continuation context limits
* Dirty-tree protection
* Explicit staging
* Commit-message validation
* Crash recovery and duplicate-commit prevention

Use a fake Cursor executable for deterministic integration tests. Do not require live Cursor access in the automated test suite.

---

## 15. Documentation

Document:

1. Installation and Cursor CLI requirements.
2. The generic `todos/` schema.
3. How another agent should prepare the workspace.
4. CLI usage.
5. Attempts and session restarts.
6. Rules and skills behavior.
7. Review contract.
8. Streaming behavior.
9. Git safety.
10. Resume behavior.
11. Known limitations.

Include a minimal example workspace.

---

## 16. Delivery Requirements

Before implementation:

1. Inspect repository architecture and conventions.
2. Inspect applicable rules and skills.
3. Inspect the installed Cursor CLI and its actual stream schema.
4. Produce a concise implementation plan.

Deliver:

* Working Python CLI
* Typed workspace schema
* Scheduler
* Cursor process adapter
* Incremental stream parser
* Colorized output
* Work and independent review phases
* Logical attempt and session restart handling
* Persistence and resume support
* Safe Git commits
* Tests
* Documentation
* Example `todos/` workspace

Do not stop after scaffolding. Implement and validate the complete end-to-end workflow.
