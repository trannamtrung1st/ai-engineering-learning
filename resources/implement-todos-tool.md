# Implement the TODO Execution Tool

Implement a production-quality Python tool that executes a structured project backlog using Cursor Agent CLI.

The tool must be deterministic, resumable, observable, testable, and safe to rerun after interruption.

Do not build this as one large script. Use typed models, clear modules, explicit interfaces, structured errors, and automated tests.

---

# 1. Objective

Create a Python CLI that:

1. Loads work items from a structured `todos/` workspace.
2. Validates the backlog, dependencies, schemas, and referenced files.
3. Selects the next executable item.
4. Runs Cursor Agent CLI to implement it.
5. Runs a separate independent review session.
6. Retries incomplete work using logical attempts.
7. Restarts interrupted Cursor sessions without incorrectly consuming logical attempts.
8. Marks an item complete only after successful review and final validation.
9. Creates one clean Git commit for each completed item.
10. Streams Cursor CLI activity as readable, colorized console output.
11. Persists sufficient state and artifacts to resume safely after crashes or timeouts.
12. Allows controlled backlog restructuring when repository reality requires it.
13. Requires Cursor sessions to inspect and follow applicable repository rules and skills.

The Python orchestrator is the authority for:

* Item selection
* State transitions
* Retry accounting
* Review acceptance
* Git staging
* Commit creation
* Completion status

Cursor Agent must not directly mark items complete or create commits.

---

# 2. Required Workspace

Use this structure unless the repository already has a clearly better established convention:

```text
todos/
├── manifest.yaml
├── items/
│   ├── 001-example-feature.yaml
│   ├── 002-example-fix.yaml
│   └── 003-example-refactor.yaml
├── runs/
│   └── <todo-id>/
│       ├── state.json
│       ├── attempts/
│       │   ├── 01/
│       │   │   ├── attempt.json
│       │   │   ├── work/
│       │   │   │   ├── session-01.ndjson
│       │   │   │   ├── session-01.stderr.log
│       │   │   │   ├── session-01-summary.md
│       │   │   │   └── phase-summary.md
│       │   │   └── review/
│       │   │       ├── session-01.ndjson
│       │   │       ├── session-01.stderr.log
│       │   │       ├── decision.json
│       │   │       └── phase-summary.md
│       │   └── 02/
│       │       └── ...
│       └── final-summary.md
└── archive/
```

Runtime-generated files under `todos/runs/` should normally be ignored by Git.

---

# 3. Manifest Schema

Example:

```yaml
version: 1

settings:
  max_attempts: 5
  max_session_restarts_per_phase: 2

  timeout_seconds: 1800
  review_timeout_seconds: 900
  termination_grace_seconds: 10

  auto_commit: true
  stop_on_failure: true

  continuation:
    max_characters: 20000
    max_recent_events: 100
    max_tool_output_characters: 8000

  stream:
    max_parse_errors: 10

items:
  - id: TODO-001
    file: items/001-example-feature.yaml

  - id: TODO-002
    file: items/002-example-fix.yaml
```

The manifest controls stable ordering and global settings.

Do not rely only on filename sorting.

Use explicit names such as:

```text
max_attempts
max_session_restarts_per_phase
```

Avoid ambiguous names such as:

```text
retry_count
```

---

# 4. Work Item Schema

Example:

```yaml
version: 1

id: TODO-001
title: Add account registration
type: feature

status: pending
priority: 100

depends_on: []

description: |
  Implement account registration according to the existing requirements
  and repository architecture.

acceptance_criteria:
  - Registration endpoint is implemented.
  - Input validation is present.
  - Automated tests cover success and failure cases.
  - Existing tests continue to pass.

validation:
  commands:
    - pytest
    - ruff check .

context:
  files:
    - docs/requirements.md
    - docs/system-design.md

execution:
  logical_attempts_completed: 0
  last_error: null
  last_run_at: null

result:
  completed_at: null
  commit_sha: null
  summary: null
```

Supported `type` values:

```text
feature
fix
refactor
```

Supported `status` values:

```text
pending
in_progress
blocked
done
superseded
```

Use typed Python models to validate all files.

Reject malformed files with actionable error messages.

---

# 5. CLI Interface

Provide an executable CLI such as:

```bash
python -m todos_tool run
python -m todos_tool run --todo TODO-001
python -m todos_tool status
python -m todos_tool validate
python -m todos_tool resume
```

At minimum implement:

```text
run
status
validate
resume
```

Expected behavior:

## `run`

Execute pending work items in dependency-safe order.

## `run --todo ID`

Execute one selected item.

Reject execution when unresolved dependencies prevent it.

## `status`

Display:

* Item status
* Dependency readiness
* Active attempt
* Active phase
* Active Cursor session
* Last failure
* Commit SHA for completed items

## `validate`

Validate:

* Manifest schema
* Item schemas
* Duplicate IDs
* Missing files
* Missing dependencies
* Dependency cycles
* Invalid statuses
* Invalid types
* Referenced context files
* Untracked item files
* Multiple incorrectly active items

## `resume`

Resume safely from persisted state and actual repository state.

Do not assume persisted state and Git state are perfectly synchronized.

---

# 6. Scheduling Rules

A work item is executable only when:

1. Its status is `pending`, or it is a resumable `in_progress` item.
2. Every item in `depends_on` is `done`.
3. It is not `blocked`.
4. It is not `superseded`.

Select executable items using:

1. Dependency eligibility
2. Manifest order
3. Priority as a secondary ordering signal

Detect and report:

* Duplicate IDs
* Missing dependencies
* Dependency cycles
* Missing item files
* Item files not present in the manifest
* Invalid active-state combinations

Do not silently ignore invalid backlog state.

---

# 7. Logical Attempts and Cursor Sessions

The implementation must distinguish:

1. Logical attempts
2. Work and review phases
3. Cursor sessions
4. Cursor session restarts

A logical attempt represents one complete effort to implement and review an item.

```text
LOGICAL ATTEMPT
├── WORK PHASE
│   ├── initial Cursor session
│   ├── optional restart
│   └── optional restart
└── REVIEW PHASE
    ├── initial Cursor session
    ├── optional restart
    └── optional restart
```

Default configuration:

```yaml
max_attempts: 5
max_session_restarts_per_phase: 2
```

This means:

```text
5 substantive implementation-and-review attempts
```

not:

```text
5 Cursor process launches
```

One phase may run:

```text
1 initial session + 2 replacement sessions
```

A timeout or recoverable Cursor process failure must not automatically consume a logical attempt.

---

# 8. Execution Lifecycle

The lifecycle is:

```text
SELECT ITEM
    ↓
START LOGICAL ATTEMPT
    ↓
WORK PHASE
    ↓
REVIEW PHASE
    ↓
PASS / FAIL / BLOCKED
    ↓
COMMIT / NEXT ATTEMPT / STOP
```

## Work phase outcomes

```text
work_ready
work_blocked
session_restarts_exhausted
fatal_error
```

`work_ready` means the implementation is ready for independent review.

It does not mean the item is complete.

## Review phase outcomes

```text
pass
fail
blocked
```

A logical attempt is normally consumed when:

* The work phase produces a reviewable result, and
* The review phase produces a valid decision

A failed review consumes exactly one logical attempt.

A passing review ends the attempt successfully.

---

# 9. Work Phase

Start a Cursor Agent CLI session with:

* Original work item
* Acceptance criteria
* Relevant repository context
* Applicable validation commands
* Current logical attempt number
* Previous failed-review feedback, when retrying
* Continuation context, when restarting a session
* Explicit rule and skill discovery requirements
* Explicit instruction not to commit
* Explicit instruction not to mark the item complete

The implementation session must:

1. Inspect the repository before editing.
2. Inspect applicable repository instructions.
3. Inspect relevant `.cursor` rules.
4. Inspect relevant `.cursor` skills.
5. Use available Cursor tools to perform the work.
6. Preserve valid existing changes.
7. Implement the requested behavior.
8. Run targeted validation.
9. Leave the working tree reviewable.
10. Return a concise work summary.

The work summary should include:

* Changes made
* Files changed
* Validation commands run
* Test results
* Applicable rules followed
* Applicable skills followed
* Remaining concerns
* Blocking issues, if any

The Cursor session must not commit.

---

# 10. Independent Review Phase

The review must run in a new Cursor session.

Do not use a simple continuation of the implementation session as the reviewer.

The reviewer receives:

* Original work item
* Acceptance criteria
* Current logical attempt
* Work summary
* Previous review feedback, if applicable
* Current Git status
* Current Git diff
* Required validation commands
* Applicable repository rules
* Applicable skills

The reviewer must independently:

1. Inspect the repository.
2. Inspect the actual diff.
3. Inspect applicable rules.
4. Inspect applicable skills.
5. Run or verify required tests.
6. Check every acceptance criterion.
7. Check instruction compliance.
8. Detect incomplete behavior.
9. Detect regressions.
10. Detect weak or missing tests.
11. Detect unrelated changes.
12. Return a machine-readable decision.

Keep the review phase read-only where practical.

The reviewer should not silently fix implementation problems.

A failed review should provide correction feedback for the next logical attempt.

---

# 11. Rules, Skills, and Repository Instructions

Every work and review session must inspect applicable instructions before acting.

Potential instruction sources include:

```text
.cursor/rules/
.cursor/rules/**/*.md
.cursor/rules/**/*.mdc
.cursor/skills/
.cursor/skills/**/SKILL.md
AGENTS.md
CLAUDE.md
CONTRIBUTING.md
README.md
docs/
```

## Instruction precedence

Follow instructions in this order:

1. System and Cursor runtime instructions
2. Repository-level agent instructions
3. Applicable Cursor rules
4. Applicable Cursor skills
5. Work-item requirements and acceptance criteria
6. Existing repository conventions

Higher-priority instructions override lower-priority instructions.

Do not silently ignore conflicts.

Report conflicts and follow the highest-priority applicable instruction.

## Rules

Rules are mandatory constraints when applicable.

The agent must:

1. Identify global rules.
2. Identify scoped rules relevant to the files being inspected or modified.
3. Respect glob patterns and scope metadata.
4. Re-evaluate scoped rules when work expands into another directory or file type.
5. Report ambiguous or conflicting rules.

## Skills

Skills are task-specific workflows selected when relevant.

The agent must:

1. Discover available skills.
2. Read relevant `SKILL.md` files.
3. Follow selected skill workflows.
4. Use required scripts, templates, and validation steps.
5. Avoid loading unrelated skills.

Skills do not override higher-priority rules.

## Required prompt instruction

Every generated Cursor prompt must include behavior equivalent to:

```text
Before making changes:

1. Inspect repository-level instructions and applicable files under
   `.cursor/rules/`.
2. Determine which rules apply globally and which apply to the files
   involved in this work.
3. Inspect `.cursor/skills/**/SKILL.md`, select only relevant skills, and
   follow their complete workflows.
4. State the selected rules and skills briefly.
5. If the implementation scope expands into another directory or file type,
   inspect whether additional scoped rules apply before modifying it.
6. Treat applicable rules as mandatory.
7. Use Cursor tools to inspect, implement, and validate the work.
8. Report instruction conflicts explicitly.
9. Do not commit.
10. Do not mark the work item complete.
```

## Instruction evidence

Work and review summaries should include:

```json
{
  "instructions": {
    "rules_applied": [
      {
        "path": ".cursor/rules/python.mdc",
        "scope": "Python source and test files",
        "summary": "Use typed interfaces and pytest."
      }
    ],
    "skills_applied": [
      {
        "path": ".cursor/skills/testing/SKILL.md",
        "reason": "The change requires integration tests."
      }
    ],
    "conflicts": []
  }
}
```

This is audit evidence only.

The reviewer must independently verify actual compliance.

---

# 12. Review Decision Contract

Do not determine success by searching natural-language output for words such as:

```text
done
passed
complete
```

Require the reviewer’s final response to contain a fenced JSON object with this logical schema:

```json
{
  "schema_version": 1,
  "todo_id": "TODO-001",
  "logical_attempt": 2,
  "phase": "review",
  "decision": "pass",
  "summary": "The implementation satisfies the acceptance criteria.",
  "acceptance_criteria": [
    {
      "criterion": "Registration endpoint is implemented.",
      "passed": true,
      "evidence": "Implemented in src/api/registration.py and covered by tests."
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
    "rules_checked": [
      ".cursor/rules/python.mdc"
    ],
    "skills_checked": [
      ".cursor/skills/testing/SKILL.md"
    ],
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

Allowed next actions:

```text
mark_done
retry
block
```

The Python tool must:

1. Extract the final review object safely.
2. Validate it against a typed schema.
3. Verify the item ID.
4. Verify the logical attempt.
5. Verify the phase.
6. Reject contradictory results.
7. Reject malformed or missing review JSON.
8. Reject stale review output from an earlier session.
9. Never mark an item complete solely because Cursor exited with code `0`.

A passing review requires:

* `decision == "pass"`
* `recommended_next_action == "mark_done"`
* Every acceptance criterion passed
* Every mandatory validation passed
* Instruction compliance passed
* No unresolved blocking issue exists

---

# 13. Logical Attempt Rules

A logical attempt must not increase because of:

* Cursor timeout
* Cursor process crash
* Recoverable transport failure
* Recoverable authentication refresh issue
* Recoverable stream failure
* Session restart
* Review session interruption before a valid decision exists

A logical attempt must increase when:

* Review returns a valid `fail`
* Acceptance criteria remain unmet
* Required validation fails during completed review
* The implementation is reviewable but substantively incorrect

Example:

```text
Attempt 1
  Work session 1 -> timeout
  Work session 2 -> completed
  Review session 1 -> process crash
  Review session 2 -> fail

Attempt 1 is consumed.

Attempt 2
  Work session 1 -> corrects issues
  Review session 1 -> pass

Attempt 2 succeeds.
```

This consumes two logical attempts.

---

# 14. Session Restart Rules

Each phase has an independent restart counter.

Example:

```json
{
  "todo_id": "TODO-001",
  "logical_attempt": 2,
  "phase": "work",
  "session_number": 2,
  "session_restarts_used": 1,
  "max_session_restarts": 2
}
```

The initial session is not a restart.

## Recoverable session failures

Examples:

* Timeout
* Unexpected Cursor CLI termination
* Recoverable transport failure
* Recoverable authentication failure
* Broken output stream
* Missing final output due to process termination
* Structured output becoming temporarily unusable

## Non-recoverable failures

Examples:

* Cursor CLI not installed
* Unsupported CLI capability
* Invalid repository state
* Invalid item schema
* Unresolvable instruction conflict
* Required credential unavailable
* Git corruption
* Unresolved merge conflict
* Unsafe working-tree state
* Explicitly blocked task

Use structured error classification.

Suggested model:

```python
class FailureKind(str, Enum):
    TIMEOUT = "timeout"
    PROCESS_CRASH = "process_crash"
    STREAM_FAILURE = "stream_failure"
    AUTH_FAILURE = "auth_failure"
    CONFIGURATION_ERROR = "configuration_error"
    REPOSITORY_ERROR = "repository_error"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
```

Each failure kind must define whether it is recoverable.

Do not classify failures using fragile arbitrary string matching alone.

---

# 15. Timeout Handling

Run Cursor CLI using:

```python
asyncio.create_subprocess_exec
```

Do not use:

```python
shell=True
```

When a session times out:

1. Emit a timeout event.
2. Send graceful termination.
3. Wait for the configured grace period.
4. Kill the process if it remains alive.
5. Continue draining output where practical.
6. Persist all complete events.
7. Persist incomplete trailing output separately.
8. Record exit information.
9. Capture Git status.
10. Capture a bounded diff summary.
11. Build continuation context.
12. Start a replacement session if restart capacity remains.

Do not reset the working tree automatically.

---

# 16. Continuation Context

A replacement Cursor session must receive:

* Original work item
* Acceptance criteria
* Current logical attempt
* Current phase
* Applicable rules and skills
* Current Git status
* Current diff summary
* Files changed so far
* Commands already executed
* Known test results
* Previous session summary
* Relevant recent assistant output
* Relevant recent tool failures
* Reason for replacement
* Explicit instruction to inspect the repository before continuing

Do not include unlimited raw transcript.

Apply limits such as:

```yaml
continuation:
  max_characters: 20000
  max_recent_events: 100
  max_tool_output_characters: 8000
```

Prefer structured summaries over blind transcript truncation.

Example continuation prompt:

```text
The previous Cursor work session ended because it exceeded its timeout.

Continue the current work phase for TODO-001. This is still logical
attempt 2. Do not restart the implementation from scratch.

Before editing:

1. Inspect the current working tree and Git diff.
2. Inspect applicable repository rules and `.cursor` skills.
3. Determine what the previous session already completed.
4. Preserve valid existing changes.
5. Correct or complete only what remains.
6. Run the required validation.
7. Do not commit.
8. Do not mark the work item complete.

Previous-session summary:
<bounded summary>

Current Git status:
<status summary>

Current diff summary:
<diff summary>
```

---

# 17. Session Restart Exhaustion

When restart capacity is exhausted:

## Attempt-specific failure

When a fresh logical attempt may reasonably succeed:

1. Record the phase failure.
2. Consume the current logical attempt.
3. Start the next logical attempt if capacity remains.

Examples:

* One session repeatedly stalls
* One continuation context becomes unusable
* One implementation direction repeatedly fails

## Environment-wide failure

When the failure is likely to affect every attempt:

1. Mark the item blocked.
2. Do not waste all logical attempts.
3. Persist the environmental reason.
4. Exit non-zero.

Examples:

* Cursor executable missing
* Authentication unavailable
* Required CLI output mode unsupported
* Repository inaccessible

---

# 18. Cursor CLI Invocation

Use Cursor CLI’s non-interactive or headless mode with native streaming JSON output.

Do not ask the model to simulate stream tags in natural-language output.

Before finalizing the command:

1. Inspect the installed Cursor CLI version.
2. Inspect `cursor --help` or equivalent.
3. Determine the actual supported non-interactive flags.
4. Determine the actual structured streaming output flags.
5. Determine the native event schema.
6. Encapsulate version-specific behavior in a `CursorClient` adapter.
7. Fail clearly when required capabilities are unavailable.

Construct commands as argument lists:

```python
command = [
    cursor_executable,
    # actual supported flags
]
```

Never interpolate untrusted content into a shell command.

Do not hardcode undocumented event assumptions in orchestration logic.

---

# 19. Streaming JSON Requirements

Cursor CLI output must be consumed incrementally.

Do not wait for `communicate()` before rendering.

Do not assume one arbitrary byte chunk equals one JSON document.

Assume newline-delimited JSON unless the installed Cursor CLI explicitly documents another framing protocol.

## stdout

The stdout reader must:

1. Read incrementally.
2. Handle split UTF-8 characters safely.
3. Buffer incomplete data.
4. Split only on complete newline boundaries.
5. Parse each complete line independently.
6. Preserve event order.
7. Flush final buffered content.
8. Persist original native events as NDJSON.
9. Normalize events for rendering.

Use an incremental UTF-8 decoder or byte-safe line reader.

Example shape:

```python
async def read_stdout(
    stream: asyncio.StreamReader,
    event_handler: EventHandler,
) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buffer = ""

    while chunk := await stream.read(4096):
        buffer += decoder.decode(chunk)

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()

            if line:
                await event_handler.handle_line(line)

    buffer += decoder.decode(b"", final=True)

    if buffer.strip():
        await event_handler.handle_line(
            buffer.strip(),
            is_final_fragment=True,
        )
```

Improve this implementation as appropriate while preserving framing correctness.

## stderr

Consume stderr concurrently.

The stderr reader must:

* Stream output immediately
* Render it as a warning or error channel
* Persist it separately
* Avoid parsing arbitrary stderr as Cursor JSON

## Malformed JSON

A malformed line must not immediately crash the entire orchestration process.

Instead:

1. Emit `[stream:error]`
2. Persist the raw line
3. Continue reading later lines
4. Increment a parse-error counter
5. Fail the session if the configured threshold is exceeded

Do not silently discard malformed lines.

## Unknown event types

Unknown event types must:

* Be persisted unchanged
* Map to a generic internal event
* Render safely
* Not crash the parser

---

# 20. Internal Event Model

Normalize native Cursor events into a stable internal model.

Suggested shape:

```python
@dataclass(slots=True)
class StreamEvent:
    timestamp: datetime
    sequence: int

    source: Literal[
        "cursor_stdout",
        "cursor_stderr",
        "orchestrator",
    ]

    category: Literal[
        "assistant",
        "thinking",
        "tool_start",
        "tool_output",
        "tool_end",
        "status",
        "warning",
        "error",
        "unknown",
    ]

    message: str | None
    tool_name: str | None
    tool_call_id: str | None
    raw_event: dict[str, Any] | str
```

Normalize events to:

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

Do not fabricate thinking content when Cursor does not emit it.

Use native tool-call IDs where available.

Do not invent unreliable correlations where no identifier exists.

---

# 21. Console Rendering

Use a library such as `rich`.

Render by normalized event category, not by parsing model-provided ANSI sequences.

Suggested visual distinctions:

```text
[assistant]    normal text
[thinking]     dim or italic
[tool:start]   emphasized tool name
[tool:output]  indented output
[tool:end]     exit status and duration
[status]       item, attempt, phase, session
[warning]      timeout or recoverable issue
[error]        fatal issue
```

Example:

```text
┌─ TODO-001 · attempt 2/5 · work · session 1/3 ─────────
[status] Starting Cursor session

[thinking] Inspecting the registration flow...

[tool:start] Read src/api/users.py
[tool:end] Completed in 42 ms

[tool:start] Run pytest tests/test_registration.py
[tool:output] 12 passed in 1.84s
[tool:end] Exit code 0

[status] Work phase completed
└────────────────────────────────────────────────────────
```

Support:

```bash
--no-color
```

Disable colors automatically when output is not attached to a compatible terminal unless explicitly forced.

Persisted logs must not contain terminal ANSI sequences.

---

# 22. Persistence and Crash Recovery

Persist state after every meaningful transition.

Required transitions include:

```text
todo_selected
attempt_started

work_session_started
work_session_timed_out
work_session_failed
work_session_restarted
work_phase_ready
work_phase_blocked

review_session_started
review_session_timed_out
review_session_failed
review_session_restarted
review_passed
review_failed
review_blocked

attempt_succeeded
attempt_failed
attempt_exhausted

commit_started
commit_completed
commit_failed

todo_done
todo_blocked
```

Write state atomically using a temporary file followed by replacement.

Suggested state:

```json
{
  "schema_version": 1,
  "todo_id": "TODO-001",
  "status": "in_progress",
  "logical_attempt": 2,
  "max_logical_attempts": 5,
  "phase": "review",
  "phase_status": "running",
  "session": {
    "number": 2,
    "restarts_used": 1,
    "max_restarts": 2,
    "started_at": "2026-07-20T08:00:00Z",
    "ended_at": null,
    "failure_kind": null
  },
  "work": {
    "completed": true,
    "summary_path": "todos/runs/TODO-001/attempts/02/work/phase-summary.md"
  },
  "review": {
    "completed": false,
    "decision": null,
    "summary_path": null
  },
  "last_transition": "review_session_restarted",
  "last_error": null
}
```

Do not overload one field to represent both substantive attempts and process launches.

## Resume behavior

On resume, inspect:

* Persisted state
* Git status
* Git diff
* Staged diff
* Latest commit
* Existing attempt artifacts

Support recovery from:

* Crash during work
* Crash after work completion
* Crash during review
* Crash after review pass
* Crash during staging
* Crash during commit
* Commit succeeded but state update failed

Prevent stale session output from completing a newer session.

Prevent duplicate commits.

---

# 23. Controlled Backlog Restructuring

The agent may discover that an item should be:

* Split
* Reordered
* Deferred
* Replaced
* Supplemented with follow-up work

Allow:

* Creating new item files
* Splitting one item into smaller items
* Adding dependencies
* Reordering later work
* Moving follow-up work into a later item
* Marking an item `superseded`
* Updating acceptance criteria when they are objectively invalid

Safeguards:

1. Preserve stable IDs where possible.
2. Never delete completed history silently.
3. Never weaken acceptance criteria silently.
4. Record a restructuring reason.
5. Validate the dependency graph.
6. Write manifest and item updates atomically.
7. Keep the active item active unless explicitly superseded.
8. Prevent restructuring from being used to falsely complete unfinished work.
9. Require the orchestrator to validate structural changes.
10. Require the reviewer to inspect restructuring when it affects completion.

New items must use the same schema.

---

# 24. Git Safety

Inspect Git state before execution.

Default behavior:

```text
Refuse to start when unrelated uncommitted changes exist.
```

Allow:

```bash
python -m todos_tool run --allow-dirty
```

When `--allow-dirty` is enabled:

1. Record initially dirty paths.
2. Track files modified during execution.
3. Stage only attributable changes.
4. Never stage unrelated pre-existing changes.
5. Fail safely when file ownership is ambiguous.

Avoid broad staging commands such as:

```bash
git add .
git add -A
```

Prefer explicit path staging:

```bash
git add -- path/to/file1 path/to/file2
```

Do not include runtime artifacts such as:

```text
todos/runs/
events.ndjson
session stderr logs
temporary state files
raw transcripts
```

unless the repository explicitly intends to version them.

---

# 25. Commit Requirements

Create exactly one commit after:

1. Review passes.
2. Acceptance criteria pass.
3. Instruction compliance passes.
4. Final validation passes.
5. The intended diff is verified.
6. No unrelated changes are staged.
7. No conflicts exist.

The item must not be marked `done` until the commit succeeds.

## Commit prefix

Map item type to Conventional Commit prefix:

```text
feature  -> feat
fix      -> fix
refactor -> refactor
```

Formats:

```text
feat: <concise change>
fix: <concise change>
refactor: <concise change>
```

Use scopes only when the repository already consistently uses them.

## Commit subject requirements

The commit subject must:

1. Be short and concise.
2. Describe the actual code or product change.
3. Use imperative mood.
4. Start with a lowercase verb after the prefix.
5. Prefer 72 characters or fewer.
6. Avoid ending punctuation.
7. Match the staged diff.
8. Describe the dominant change.
9. Remain understandable without reading the work item.
10. Avoid unrelated details.

Good examples:

```text
feat: add account registration
feat: stream cursor events
feat: support resumable execution

fix: handle incomplete json events
fix: prevent duplicate commits
fix: preserve work after timeout

refactor: separate attempts from sessions
refactor: extract stream parser
refactor: isolate git operations
```

## Prohibited commit content

Do not mention:

* AI
* Agent
* Cursor
* TODO
* Work item IDs
* Backlog
* Review loop
* Reviewer
* Attempt
* Retry
* Generated code
* Orchestrator execution
* Skills
* Rules
* Automation process

Avoid:

```text
feat: complete TODO-001
feat: implement agent-generated registration
fix: address reviewer feedback
fix: retry cursor session
refactor: improve ai workflow
```

Prefer:

```text
feat: add account registration
fix: resume execution after timeout
fix: handle session termination
refactor: separate runtime state models
```

## Commit-message generation

Generate the subject from this priority:

```text
verified staged diff
    ↓
completed acceptance criteria
    ↓
item title and description
```

Do not generate it primarily from:

* Item filename
* Item ID
* Agent summary
* Review result wording
* Retry history
* Session metadata

Recommended process:

1. Inspect staged diff.
2. Identify the dominant repository change.
3. Select the prefix from the item type.
4. Write one concise imperative subject.
5. Remove process-related language.
6. Validate the subject.
7. Confirm it matches the staged files.

## Commit body

Do not add a body by default.

A body may be used only when required by repository convention or when an important migration or compatibility implication must be explained.

The body must describe technical implications only.

It must not mention execution metadata.

## Commit-message validation

Implement a validator that checks:

* Correct prefix
* Non-empty subject
* Length limit
* No ending period
* No work-item ID
* No prohibited process language
* No generic completion wording
* Meaningful relation to staged diff

Use token-aware or word-boundary matching.

Do not use naive substring matching for short terms such as `ai`.

For example:

```text
"AI agent"        -> prohibited
"Cursor session"  -> prohibited
"TODO-001"        -> prohibited
"maintain parser" -> allowed
```

## Commit failure

If commit creation fails:

1. Do not mark the item done.
2. Persist the failure.
3. Preserve the reviewed working tree.
4. Record staged state.
5. Allow safe finalization resume.
6. Inspect whether the commit may already exist.
7. Prevent duplicate commits.

On resume inspect:

```bash
git status
git log -1
git diff
git diff --cached
```

---

# 26. Suggested Architecture

Use a package structure similar to:

```text
src/
└── todos_tool/
    ├── __init__.py
    ├── __main__.py
    ├── cli.py
    ├── config.py
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

Responsibilities:

## `CursorClient`

* CLI capability detection
* Process invocation
* Process termination
* stdout and stderr handling
* Session result construction

## `StreamParser`

* Incremental framing
* UTF-8 decoding
* Native JSON parsing
* Parse-error tracking

## `EventNormalizer`

* Native-to-internal event mapping
* Unknown event handling
* Tool lifecycle correlation

## `ConsoleRenderer`

* Terminal presentation only
* No orchestration decisions

## `Orchestrator`

* Lifecycle
* Logical attempts
* Phase control
* Restart policy
* Completion coordination

## `Persistence`

* Atomic state
* Run artifacts
* Recovery metadata

## `GitService`

* Repository inspection
* Dirty-tree handling
* Diff ownership
* Explicit staging
* Commit creation
* Duplicate-commit prevention

## `Reviewer`

* Decision extraction
* Schema validation
* Contradiction detection

## `ContinuationBuilder`

* Bounded continuation context
* Previous-session summarization
* Git-state inclusion

## `Scheduler`

* Dependency validation
* Readiness selection
* Cycle detection

## `CommitMessageService`

* Prefix mapping
* Diff-based subject generation
* Prohibited-language validation

Avoid circular dependencies.

Use type hints throughout.

Use structured exceptions instead of broad generic exception handling.

---

# 27. Orchestrator Semantics

Implement behavior equivalent to:

```python
async def execute_todo(todo: TodoItem) -> TodoResult:
    for attempt_number in range(1, config.max_attempts + 1):
        await state.start_attempt(attempt_number)

        work_result = await execute_phase_with_restarts(
            phase="work",
            todo=todo,
            attempt_number=attempt_number,
            previous_attempt_feedback=state.last_review_feedback,
        )

        if work_result.blocked:
            return await block_todo(work_result.reason)

        if not work_result.completed:
            await state.fail_attempt(
                reason=work_result.failure_reason,
                category="work_phase_failure",
            )
            continue

        review_result = await execute_phase_with_restarts(
            phase="review",
            todo=todo,
            attempt_number=attempt_number,
            work_result=work_result,
        )

        if review_result.blocked:
            return await block_todo(review_result.reason)

        if not review_result.completed:
            await state.fail_attempt(
                reason=review_result.failure_reason,
                category="review_phase_failure",
            )
            continue

        if review_result.decision == "pass":
            return await finalize_and_commit(
                todo=todo,
                work_result=work_result,
                review_result=review_result,
            )

        await state.fail_attempt(
            reason=review_result.summary,
            category="review_failed",
        )

        await state.store_review_feedback(
            build_next_attempt_feedback(review_result)
        )

    return await exhaust_todo_attempts(todo)
```

Phase restart behavior should be equivalent to:

```python
async def execute_phase_with_restarts(
    phase: Phase,
    todo: TodoItem,
    attempt_number: int,
    **context: object,
) -> PhaseResult:
    max_sessions = config.max_session_restarts_per_phase + 1
    continuation: ContinuationContext | None = None

    for session_number in range(1, max_sessions + 1):
        result = await cursor_client.run_session(
            phase=phase,
            todo=todo,
            attempt_number=attempt_number,
            session_number=session_number,
            continuation=continuation,
            **context,
        )

        if result.completed:
            return result

        if not result.failure.recoverable:
            return PhaseResult.failed(result.failure)

        if session_number == max_sessions:
            return PhaseResult.failed(
                SessionRestartsExhausted(
                    phase=phase,
                    last_failure=result.failure,
                )
            )

        continuation = continuation_builder.build(
            todo=todo,
            phase=phase,
            attempt_number=attempt_number,
            previous_session=result,
            repository_state=git_service.inspect(),
        )

    raise AssertionError("unreachable")
```

The concrete implementation may differ, but the semantic separation must remain.

---

# 28. Testing Requirements

Add unit and integration tests.

Use a fake Cursor executable in integration tests.

Do not require live Cursor API usage in the automated test suite.

The fake executable must support deterministic:

* NDJSON events
* Split JSON events
* Split UTF-8 characters
* stderr output
* Malformed lines
* Unknown event types
* Delayed output
* Timeout behavior
* Process crashes
* Valid review decisions
* Invalid review decisions

## Schema and scheduling tests

Test:

* Valid manifest
* Invalid manifest
* Valid item
* Invalid status
* Invalid type
* Duplicate IDs
* Missing files
* Missing dependencies
* Dependency cycles
* Dependency-safe ordering
* Superseded items
* Blocked dependencies

## Stream parser tests

Test:

* One JSON event per chunk
* Multiple events in one chunk
* One event split across many chunks
* Split multibyte UTF-8 characters
* Blank lines
* Malformed JSON followed by valid JSON
* Unknown event types
* Final line without newline
* Concurrent stderr
* Large tool output
* Parse-error threshold
* No ANSI sequences in persisted logs

## Process lifecycle tests

Test:

* Successful process
* Non-zero exit
* Timeout
* Graceful termination
* Forced kill
* Cancellation cleanup
* Recoverable restart
* Non-recoverable failure
* Restart exhaustion

## Logical attempt accounting tests

Test:

* Work timeout followed by success does not increment attempt
* Review timeout followed by success does not increment attempt
* Three sessions inside one phase still count as one attempt
* Review failure increments attempt exactly once
* Review pass ends execution
* Restart counters reset for a new phase
* Restart counters reset for a new logical attempt
* Maximum attempts use logical attempts, not process launches

## Review tests

Test:

* Valid pass
* Valid fail
* Valid blocked result
* Missing JSON decision
* Malformed JSON
* Wrong item ID
* Wrong logical attempt
* Wrong phase
* Pass with failed criterion
* Pass with failed validation
* Pass with instruction violation
* Contradictory decision and action
* Stale review output

## Continuation tests

Test:

* Includes current Git state
* Includes current logical attempt
* Includes applicable rules and skills
* Excludes unlimited raw transcript
* Preserves valid current changes
* Summarizes timeout reason
* Respects character and event limits

## Git tests

Test:

* Clean-tree execution
* Dirty-tree refusal
* `--allow-dirty`
* Explicit staging
* Unrelated change protection
* No commit after failed review
* No commit after validation failure
* Correct prefix mapping
* Commit-message length validation
* Prohibited language validation
* No ending period
* Commit failure does not mark done
* Resume after commit failure
* Duplicate-commit prevention

## Recovery tests

Test:

* Crash during work resumes same phase
* Crash after work completion resumes review
* Crash during review resumes review
* Crash after review pass resumes finalization
* Crash during staging
* Crash during commit
* Commit succeeds but state update fails
* Stale session cannot finalize active state

---

# 29. Documentation

Add documentation covering:

* Installation
* Python requirements
* Cursor CLI prerequisites
* Cursor CLI capability detection
* Authentication assumptions
* Workspace format
* Manifest schema
* Item schema
* CLI commands
* Scheduling behavior
* Logical attempts
* Session restarts
* Timeout behavior
* Continuation behavior
* Rule and skill discovery
* Review contract
* Stream event normalization
* Git safety
* Commit-message rules
* Crash recovery
* Backlog restructuring
* Example run
* Known limitations

Include a minimal runnable example backlog.

---

# 30. Final Acceptance Criteria

The implementation is complete only when all of the following are true:

1. The backlog can be loaded and validated.
2. Items execute in dependency-safe order.
3. Logical attempts and Cursor sessions are modeled separately.
4. A timeout does not automatically consume a logical attempt.
5. Work and review phases have independent session-restart budgets.
6. Each logical attempt contains a completed work phase and independent review phase.
7. A failed substantive review consumes exactly one logical attempt.
8. A passing review is required before completion.
9. Review decisions use a validated machine-readable contract.
10. Malformed or contradictory review decisions cannot complete an item.
11. Applicable repository rules are discovered and followed.
12. Relevant `.cursor` skills are discovered and followed.
13. Scoped rules are re-evaluated when modified-file scope changes.
14. Review independently verifies rule and skill compliance.
15. Cursor native streaming output is consumed incrementally.
16. Split JSON and split UTF-8 sequences are handled correctly.
17. stdout and stderr are consumed concurrently.
18. Malformed stream lines are persisted and handled safely.
19. Unknown native event types do not crash the tool.
20. Console output clearly distinguishes item, attempt, phase, and session.
21. Continuation context is bounded and structured.
22. Replacement sessions inspect and preserve valid existing work.
23. State is persisted atomically after meaningful transitions.
24. Resume logic handles crashes during work, review, staging, and commit.
25. Stale session output cannot finalize newer state.
26. Backlog restructuring is controlled, validated, and auditable.
27. Unrelated user changes are never staged accidentally.
28. Each completed item creates exactly one commit.
29. Commit messages describe only the actual repository change.
30. Commit messages are short, concise, and imperative.
31. Commit messages do not mention AI, agents, Cursor, TODOs, reviews, attempts, or retries.
32. Commit messages are generated from the verified staged diff.
33. Runtime logs and session artifacts are excluded from product commits.
34. A failed commit cannot result in completed status.
35. Resume logic prevents duplicate commits.
36. Unit and integration tests cover the critical lifecycle.
37. Documentation explains setup, execution, recovery, and limitations.

---

# 31. Required Implementation Process

Before editing code:

1. Inspect the repository architecture.
2. Inspect repository conventions.
3. Inspect repository-level instructions.
4. Inspect `.cursor/rules`.
5. Inspect `.cursor/skills`.
6. Inspect the installed Cursor CLI version and help output.
7. Determine the actual structured-output event schema.
8. Produce a concise implementation plan.
9. Implement in small coherent modules.
10. Add tests alongside the implementation.
11. Run focused tests during development.
12. Run the full relevant test suite before completion.
13. Inspect the final diff.
14. Document any version-specific assumptions.

Do not stop after scaffolding.

Deliver:

* Working Python CLI
* Typed schemas
* Dependency scheduler
* Cursor process adapter
* Incremental streaming parser
* Event normalization
* Colorized renderer
* Logical attempt and session model
* Independent review flow
* Rule and skill discovery flow
* Continuation and recovery logic
* Git safety
* Concise commit-message generation
* Unit tests
* Integration tests
* Documentation
* Example backlog

At completion, report:

* Architecture implemented
* Files added or changed
* Cursor CLI invocation selected
* Native events observed
* Event normalization mapping
* Tests executed
* Validation results
* Remaining limitations
* Version-specific assumptions
