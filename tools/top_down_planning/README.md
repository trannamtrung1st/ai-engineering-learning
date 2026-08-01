# Top Down Planning (`tdp`)

Planning and production orchestration: receive an input and output goal, build a top-down plan, review and validate it, produce output in coherent batches, and resolve a final quality outcome.

Specification: [`docs/spec.md`](docs/spec.md) · Resume ops:
[`docs/resume-batch-checklist.md`](docs/resume-batch-checklist.md) · §19 crosswalk:
[`docs/implementation-plan-crosswalk.md`](docs/implementation-plan-crosswalk.md)

## Quickstart

```bash
cd tools/top_down_planning
python -m pip install -e ../core_tools -e ".[dev]"
cd ../..

tdp agent help
tdp agent schema plan-transaction
tdp agent example expand-branch

tdp run --config tools/top_down_planning/examples/top-down-planning.yaml
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml --until validated
tdp status --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp resume --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp resume --run <run-id> --until completed --config tools/top_down_planning/examples/top-down-planning.yaml
```

The default provider is `cursor` (requires the Cursor CLI on PATH). Unit and integration
tests default to `stub` via `tests/helpers.minimal_resolved_config()` and
`create_run_kwargs()`; use `script_turn()` with `StubProvider` for deterministic
orchestration coverage — not as an interactive `tdp run` quickstart.

## Architecture layers

| Layer | Package | Responsibility |
| --- | --- | --- |
| Core domain | `domain/` | Pure models and rules: plan tree, dependencies, validation, production state, outcomes. No CLI, provider, or persistence concerns. |
| Orchestrator | `orchestrator/` | Lifecycle transitions: plan → review → validate → produce → amend → review output → resolve outcome. |
| Agent tool | `agent_tool/` | `tdp agent` CLI service layer: atomic domain operations with schema validation and revision checks. |
| Shared infra | [`core_tools`](../core_tools) | Provider adapters; config merge/overrides, workspace paths, resource/skill loading, allowlist validation; atomic writes and digests; revision helpers; CLI emit/request/runs-dir resolution; minimal JSON Schema validation. |
| Persistence | `persistence/` | `RunStore` interface and `FileRunStore` for canonical snapshots, events, and session references. |
| CLI | `cli/` | User-facing (`tdp run`, `tdp resume`, …) and agent-facing (`tdp agent …`) command wiring. |
| Config | `config/` | TDP schema (`DEFAULT_CONFIG`, allowed override paths) and `resolve_config`. |

## Provider

Provider adapters live in `core_tools.provider`. Resolved configuration selects the adapter:

```yaml
provider:
  name: cursor          # cursor | stub
  binary: /path/to/agent  # optional; otherwise agent or cursor-agent on PATH
  skip_probe: false     # skip CLI version probe when true
```

Per-role model selection uses `agent_context.<role>.model`, falling back to `agent_context.default.model`. `model: auto` means no explicit Cursor `--model` argument.

- `cursor` — thin Cursor CLI adapter (`--print --output-format stream-json --trust --approve-mcps --force`). `--force` is required so non-interactive turns can run shell/`tdp agent …` tools; without it those calls are rejected. Provider session ids are stored on structured session bindings under `run.sessions` (`primary_planner`, `primary_producer`) and on each review loop's `reviewer_binding`: each binding carries `session_instance_id`, `generation`, `provider_session_id`, `state`, `role`, and `kind`. The Cursor adapter may return transient `cursor-pending-*` ids before the CLI subprocess starts; bindings keep those in `state: starting` until a durable id is known, then transition to `state: bound`. `session_provider_id_bound` lineage events emit only for durable ids. `get_session_reference` is available on the provider for durable ref export. Bounded reviewer sessions are released from the in-memory registry when a terminal review decision is recorded; after each phase step (including user cancel via Ctrl+C), `RunEngine` emits `[session:end]` and calls `terminate_all_sessions()` only for sessions still in that registry. Later turns re-bind persisted ids through Cursor `--resume` when the in-memory adapter was torn down between phase steps.
- `stub` — deterministic scripted turns for **tests only**; call `script_turn()` before each provider turn.

Production runs default to `cursor`. Test helpers default to `stub`; override
`provider.name` in a test only when exercising cursor-specific behavior.

## Console observability

`tdp run` and `tdp resume` always stream progress logs to **stderr** (including with `--stream-json`). Final structured command payloads remain on **stdout**. The reusable observability layer lives in `core_tools.observability`; TDP wires it through CLI flags, provider event callbacks, and an observing run-store decorator that mirrors `events.jsonl` audit records to the console.

```bash
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml \
  --log-level verbose --color auto

tdp run --config tools/top_down_planning/examples/top-down-planning.yaml \
  --stream-json | jq .    # progress on stderr; JSON payload on stdout

tdp run --config tools/top_down_planning/examples/top-down-planning.yaml \
  --log-format jsonl --no-color

tdp resume --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml \
  --agent-transcript   # optional agent-transcript.jsonl under the run dir
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--color auto\|always\|never` | from config / `auto` | Color mode (`--no-color` ⇒ `never`) |
| `--log-level quiet\|normal\|verbose\|trace` | from config / `normal` | Verbosity |
| `--log-format console\|jsonl` | from config / `console` | Human console vs JSONL on stderr |
| `--agent-text` / `--no-agent-text` | from config / on | Show thinking/response text (streamed incrementally) |
| `--timestamps` / `--no-timestamps` | from config / off | Category prefix on the first line of each event; optional timestamp when enabled (streaming `thinking`/`response` blocks share one prefix) |
| `--agent-transcript` / `--no-agent-transcript` | from config / off | Persist redacted provider transcript |

Observability can be set in YAML under `observability` (same file as orchestration config). Precedence for presentation settings: built-in defaults → YAML → `--set` → explicitly supplied dedicated CLI flag (omitted flags do not override YAML). Changing observability or `runtime.runs_dir` does not invalidate resume; `digests.config_contract` and `digests.config_execution` exclude those presentation fields.

Provider thinking and response text is normalized from Cursor `stream-json` (`text` field or `message.content`), deduplicated when cumulative, and printed incrementally as new characters arrive. Empty thinking chunks are dropped. Explicit `\n` in agent text breaks lines within a thinking/response block; multiple sentences without newlines stay on one line until another category interrupts.

Tool invocations print as `[tool:start]` and `[tool:end]` with a concise summary from the normalized provider event (`summary` field). Cursor native tools (including shell `tdp agent …` invocations) are summarized from the nested `tool_call` payload. `tool_call` events with `subtype: started` or `completed` reach the console bridge; `tool_result` events and duplicate lifecycle events for the same `call_id` are dropped.

Console output prints `[category]` once per discrete event block (optional `[timestamp]` when `show_timestamps` is enabled). `thinking` and `response` stream incrementally with one prefix per block; explicit `\n` in agent text breaks lines within the block.

Agent session lifecycle: `[session:start]` on `planner_session_started` / `producer_session_started` / `reviewer_session_started` audit events (`phase`, `role`, `run_id`, `session_id`, `model` required); `[session:resume]` on `*_session_resumed` with the same fields; `[session:end]` on `reviewer_session_ended` when a bounded reviewer turn records a terminal decision, and from engine teardown for any provider session still in the in-memory registry after each blocking phase step or Ctrl+C cancel (primary planner/producer sessions have no durable end audit). `model` is the provider-resolved CLI model label (`auto` when no explicit `--model` is passed). Providers attach the same `model` label to normalized stream events; agent discrete console events (`tool:start`, `tool:end`, `retry`, `error`) surface it from those events. Run-level CLI messages use `[run:start]` and `[run:resume]`; persisted `run_created` audit events map to `[run:start]`.

`events.jsonl` remains a concise orchestration audit log (no agent prose). Capability tokens, secrets, and oversized payloads are redacted at every log level.

`tdp run` and `tdp resume` handle Ctrl+C without a traceback: the engine stops provider subprocesses, emits a `[session:cancel]` line on stderr, emits `[session:end]` for each active provider session, pauses the run with `stop.code: user_cancelled` (`status: paused`), and exits with code 130. With `--stream-json`, stdout carries `{"cancelled": true, "reason": "cancelled by user", ...}`. Resume with `tdp resume` clears the pause and continues the same run.

## Import boundaries

- `domain` must not import `cli`, `persistence`, `orchestrator`, or `core_tools`.
- Shared provider/config/persistence primitives live in [`core_tools`](../core_tools); TDP imports them at orchestrator, CLI, and persistence boundaries.
- Project-specific extensions stay outside the core package.

## User CLI

```bash
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml --set planning.max_depth=5
tdp status --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp inspect --run <run-id> --view active --config tools/top_down_planning/examples/top-down-planning.yaml
tdp validate --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp resume --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
```

Configuration precedence: built-in defaults → YAML file → repeated `--set path=value` overrides → dedicated CLI flags when explicitly supplied. Unknown paths in YAML or `--set` are rejected. Resolved configuration is materialized to `<runs-root>/<run-id>/resolved-config.yaml`. Resume binds approvals to `digests.config_contract` and limit changes to `digests.config_execution`; both exclude `observability` and `runtime.runs_dir`. CLI invocation metadata is persisted separately in `invocation.json`.

### Path resolution

Config files may live anywhere. `project.workspace` is the canonical workspace root for a run.

- `project.workspace` resolves against the **process working directory** (defaults to process cwd when omitted).
- `run.input_refs`, `run.output_goal_file`, and all `agent_context.*.resources` / `agent_context.*.skills` / `agent_context.*.guidance` file entries resolve against the resolved `project.workspace`.
- `runtime.runs_dir` resolves against the process working directory.

Absolute paths are used directly. Launch `tdp` from the intended working directory (for example the repository root).

Use either `run.output_goal` (inline text) or `run.output_goal_file` (path to a UTF-8 file), not both. File-backed goals resolve against `project.workspace`. At run start the file contents are loaded into `plan.output_goal`; the path stays in resolved config. Resume re-reads the file and rejects digest mismatches if the content changed.

### Run contracts and agent context

Each field has one responsibility:

```text
run.input_refs
    Authoritative problem and specification inputs.

run.output_goal / run.output_goal_file
    Authoritative deliverable contract.

agent_context.default
    Shared supporting context inherited by every role (model, guidance, resources, skills).

agent_context.<role>
    Role-specific supporting context. Each role section may override the shared model and
    add guidance, resources, and skills on top of agent_context.default.

project.workspace
    Canonical workspace root.
```

`run.input_refs` and the resolved output goal are supplied automatically to planner, producer, and reviewer sessions. Do not repeat them under `agent_context.*.resources`.

Use guidance for role behavior preferences. Use `run.input_refs`, boundaries, acceptance, and output_goal for authoritative work contracts. Use resources for supporting reference material and skills for reusable methods.

Guidance is additive with `agent_context.default`, attached to fresh role sessions, and included in the supporting-context digest. It does not change run acceptance, create runtime enforcement, or introduce new lifecycle transitions. Each guidance entry is exactly one of `{text: ...}` or `{file: ...}`.

`--set agent_context.<role>.guidance=…` must be a JSON array of objects (the `--set` parser does not accept YAML mapping syntax inside list items). Use double quotes and escaped JSON, for example:

```bash
tdp run --config config.yaml \
  --set 'agent_context.producer.guidance=[{"text":"Work in coherent batches."},{"file":"docs/producer-guidance.md"}]'
```

In YAML config files, use normal list-of-mappings syntax (`- text: >` or `- file: path`).

```yaml
project:
  workspace: .

run:
  input_refs:
    - configs/task.md
  output_goal_file: configs/output-goal.md

agent_context:
  default:
    model: auto
    guidance: []
    resources:
      - AGENTS.md
    skills:
      - .agents/skills/common/

  planner:
    model: reasoning-model
    resources:
      - docs/planning-guidelines.md
    skills:
      - .agents/skills/top-down-planning/

  producer:
    model: coding-model
    guidance:
      - text: >
          Work in coherent batches. Consider focused review and useful
          Git checkpoints; skip a commit when that is better judgment.

  reviewer:
    model: review-model
```

Role `guidance`, `resources`, and `skills` are additive with `agent_context.default`. Skills are path-only bundles: a file path or a directory containing `SKILL.md`. Effective context is attached to fresh planner, producer, and reviewer sessions.

Run contracts bind via `digests.input` and `digests.output_goal` at run creation. Supporting agent context uses a **spec vs snapshot** split:

- `digests.context_spec` — stable declarations (role models, guidance entries, resource path selection, skill paths) plus the resolved snapshot exclusion policy (`context_snapshot.excludes` and built-in policy version).
- `digests.context_snapshot` — materialized resource file bytes, skill contents, and guidance text/file digests, persisted in `context_snapshot_binding` on the run record.

Resume always validates `context_spec`. `context_snapshot` is skipped only during the `production` phase so in-flight authorized mutations are allowed. Each `production apply` validates cumulative snapshot drift against the candidate batch (including proposed outputs) and rejects incomplete evidence before persistence. Production completion re-validates the same invariant, rebases `context_snapshot` when authorized, emits `context_snapshot_rebased` after the run record is persisted, then enters `whole_output_review`. Unauthorized workspace changes block apply retry or completion and later phase entry.

### Context snapshot exclusions and binding

The context snapshot protects supporting agent resources from silent drift: each included file keeps a per-file SHA-256 digest so production can attribute intentional edits to evidence without treating unrelated workspace noise as authorized. Skill digests (and guidance digests when configured) stay in the binding because those surfaces are snapshot-bound today; exclusions apply only to **resource** materialization, not to skills or guidance.

Without exclusions, directory resources that include `__pycache__` / `*.pyc` / tool caches cause false-positive unauthorized mutations at production completion after imports or tests. Configure exclusions under `context_snapshot` (default-on when omitted):

```yaml
context_snapshot:
  excludes:
    defaults: true   # built-ins: **/__pycache__/, **/*.py[cod], **/.pytest_cache/, **/.mypy_cache/, **/.ruff_cache/
    patterns:        # ordered gitignore/gitwildmatch patterns; later entries override earlier ones
      - "generated/"
      - "!generated/schema.json"
```

- Empty `patterns: []` does **not** disable defaults; set `defaults: false` to turn built-ins off.
- Patterns match canonical workspace-relative POSIX paths. Negations (including overrides of built-ins), `*`, `**`, root anchors (`/rooted.txt`), and directory-only patterns (`dir/`) follow the gitignore dialect via a pathspec adapter.
- TDP does **not** inherit `.gitignore`. Exclusion policy participates in `context_spec` identity, so changing defaults, patterns, pattern order, or the built-in policy version changes the context-spec digest.
- Direct file resources always bind (including missing files with a missing-resource sentinel digest), even when they match an exclude pattern. Files discovered through directory or glob expansion are filtered. Glob expansion stays file-only / non-recursive as before.
- Resource paths must resolve inside the workspace; absolute paths, unresolved `..`, and symlink escapes are rejected during materialization (same contract as production evidence refs). External paths fail at collection, not as silent unauthorized drift.
- Binding keys are workspace-relative POSIX paths (`/`); digests are bare lowercase hex (no `sha256:` prefix). Production evidence `ref` values use the same canonical relative path model. The persisted binding is a compact map:

```json
{
  "resource_digests": {"src/a.py": "<64-hex>"},
  "skill_digests": {"skills/demo/SKILL.md": "<64-hex>"},
  "guidance_digests": [{"path": "docs/g.md", "text": "...", "digest": "<64-hex>"}]
}
```

List-shaped `{path, digest}` entries, absolute path keys, and a binding-level `workspace` field are rejected; recreate the run. Config document `version` is unrelated to run-record `schema_version` (currently `3`). Unsupported or missing run `schema_version` fails load with a recreate message — there is no automatic migrator. See [`docs/resume-batch-checklist.md`](docs/resume-batch-checklist.md) for the coordinated v3 deployment gate. Prefer snapshot excludes over

Snapshot excludes apply only to **context snapshot** resource materialization (`SnapshotPolicy.collect`). Agent session resource manifests still expand directories recursively and may list `__pycache__` / `.pyc` paths from `resolve_expanded_path_list`; that packaging surface is intentionally unchanged — use snapshot excludes for integrity binding, not for agent manifest hygiene.

Phase-entry audit events distinguish precondition failures from orchestrator start:

- `phase_entry_attempted` — engine iteration selected a phase and began resume precondition checks.
- `phase_entry_blocked` — precondition validation rejected entry (`error_code`, optional `digest_kind`, shortened `expected_digest` / `actual_digest`).
- `whole_*_review_started` / `*_scope_review_started` — mandatory review orchestrator actually started (after preconditions pass). Concise review audit companions include `review_findings_reported`, `review_revision_required`, `review_incomplete`, `review_advisory_handoff_started`, `review_finding_action_recorded`, and `review_challenge_submitted`.

`[session:end]` for bounded reviewers maps from durable `reviewer_session_ended` audit events (see Console observability above). Primary planner/producer sessions do not persist a durable end audit.

Example from a repository root:

```yaml
# configs/my-project.yaml
runtime:
  runs_dir: .tdp/runs
project:
  workspace: .
run:
  input_refs:
    - configs/task.md
  output_goal: Deliver the requested output.
```

```bash
cd /path/to/repo

tdp run --config configs/my-project.yaml

tdp resume --run <run-id> --config configs/my-project.yaml
```

With `project.workspace: .` and `runtime.runs_dir: .tdp/runs`, a run launched from `/path/to/repo` uses workspace `/path/to/repo` and runs root `/path/to/repo/.tdp/runs` even when the config file is stored under `configs/`. Config location does not affect workspace or input path resolution.

`tdp run` prints startup diagnostics **before** the first provider turn blocks (unless `--stream-json`): working directory, config file, workspace, runs root, runs root source, and run path. The same diagnostics are repeated in the final status line when planning construction returns.

### Run store location

The run store root is the directory that contains all run folders (`<runs-root>/<run-id>/`). New runs receive lexicographically sortable ids in the form `run-YYYYMMDDTHHMMSS-<6hex>` (UTC timestamp plus random suffix), for example `run-20260730T145612-e453e4`. Configure the store root with optional YAML:

```yaml
runtime:
  runs_dir: .tdp/runs   # relative paths resolve against the process working directory
```

`tdp run` requires an explicit run store: set `runtime.runs_dir` in the config, pass `--runs-dir`, or export `TDP_RUNS_DIR`. Later commands may also use `--config` to locate the store via `runtime.runs_dir`.

Resolution precedence:

1. `--runs-dir` on the command line
2. `$TDP_RUNS_DIR` environment variable
3. `runtime.runs_dir` in the YAML config (or `--set runtime.runs_dir=...` on `tdp run`)
4. `./runs` under the current working directory

`tdp run` creates the store root when needed. Read-only commands (`status`, `inspect`, `validate`, `tdp agent …`) do not create a missing store.

When the orchestrator starts a provider session, it exports `TDP_RUNS_DIR` and a session-scoped `TDP_CAPABILITY_TOKEN` to provider subprocesses **before** any turn where the agent may run mutating `tdp agent …` commands. Reviewer sessions allocate a provider session id first, bind the capability token, then deliver the review package on the next turn. Mutating commands require the capability token; authorization is bound to run phase, role, provider session, and (for reviewers) review loop — not a self-declared `--role` flag. Capability records store only a hash of the secret; tokens are revoked when turns, loops, or phases end.

Planner, producer, and reviewer packages include `protocol_instructions` (role behavior rules) and `tool_instructions` (`tdp agent` command templates). The provider adapter surfaces `protocol_instructions` at the top of the prompt so agents do not substitute host IDE planning artifacts for persisted `tdp agent` mutations.

Agents mutate run state only through `tdp agent …` shell commands (which persist to the run store). The orchestrator does not intercept provider tool events for plan/production/review mutations. After each provider turn it observes store changes (pending focused reviews, applied batches, review decisions) and resolves phase completion from explicit signal tokens (`candidate_plan_ready`, `batch_complete`, `amendment_revision_ready`, etc.) in assistant text or `done.signal` metadata.

`tdp run` supports `--until plan|validated|completed` (default `plan`). `tdp resume` advances one phase step by default, or loops to `--until` when set. Both use the central `RunEngine` continuation loop.

`tdp resume --check` builds and prints the same structured resume plan summary as apply mode without mutating the run, saving config, appending events, or contacting the provider. Use `--config` and/or repeatable `--set path=value` to evaluate limit increases; diagnostics include consumed usage, stored limit, candidate limit, and remaining budget for exhausted limits. Interrupt taxonomy: graceful Ctrl+C pauses the run with `stop.code: user_cancelled`; abrupt process loss may leave a paused or running record depending on timing. Paused runs require accepted `prepare_resume` / `apply_resume_plan_atomically` before `RunEngine.continue_run` proceeds.

Persistence uses journaled `RunStore.commit()` for multi-file mutations: staged writes, per-file digests and backups, journal records replacements only after successful `Path.replace()`, digest-verified recovery, per-run `.commit.lock` serialization around commits and commit-managed reads (`load_run`, `load_plan`, `load_production`, `load_events`, `load_review`, `list_reviews`), and rollback or completion of pending event appends after a crash. Each run directory includes `invocation.json` (latest CLI invocation metadata, not part of semantic config digests). Output evidence records bind artifact content (`sha256`, `size`, `media_type`, `captured_at`) and snapshot approved files under immutable UUID paths in the run store. Evidence IDs are unique across the full run history.

`tdp run` creates the run store and drives the run until the requested milestone or a limit/failure. On the default `plan` target, success means phase `whole_plan_review`. `tdp resume` validates digests and session references before continuing.

Whole-plan review: the orchestrator allocates a fresh reviewer session id, binds a capability token, delivers the bounded review package, and consumes the review turn. Mandatory gates use two repeatable modes — verification (`finding_verification`, session resume) and fresh scope review (`scope_review`, new session) — with `initial_review` as the first discovery gate. The typical clear path runs initial discovery, then fresh scope discovery — two `reviewer_session_started` events, two `reviewer_session_ended` events, and zero `reviewer_session_resumed`. Revision paths emit `reviewer_session_resumed` for verification rechecks before starting a fresh scope-review session. There is no hard cap of two total review executions; `limits.whole_plan_review.max_revision_cycles` and `max_scope_review_rounds` bound verification and scope-review rounds independently. Clear initial approval still requires a separate fresh `scope_review` — finding closure alone is not final approval. Stage responds require `stage` plus Result Contract fields (`tdp agent example review-respond-initial`, `review-respond-verification`, `review-respond-scope`). Each loop binds findings to the current plan revision, resumes the same primary planner for revisions after `changes_requested`, and requires verification recheck (`finding_verification` delivery) before scope review when findings were raised. Review packages include an optional `rubric` on initial review only; fresh scope review omits the full quality rubric. Reviewer protocol and stage guidance prioritize plan correctness and internal consistency. Review responses and audit events expose `revise_at` plus required/optional finding counts and ids. After the gate completes, deterministic `validate_plan(..., mode="approval")` must pass before the run advances to `plan_validated`. Limit exhaustion pauses the run with `stop.code: limit_exhausted`; resume with an increased limit continues the same run.

Focused reviews: during `planning` or `production`, the primary planner or producer may request optional `focused_plan` or `focused_output` reviews via `tdp agent review request` with bounded `scope.item_ids`. Each request starts a fresh reviewer session; the same reviewer rechecks within the loop. Focused approval does not substitute for mandatory whole-plan or whole-output gates. Limits use `review.focused_plan.enabled`, `review.focused_output.enabled`, and `limits.focused_plan_review` / `limits.focused_output_review`. Unresolved required findings in an active focused loop block `candidate_plan_ready`, `production_apply`, and `submit-completion` for overlapping items. Plan `ready` snapshots block on `focused_plan` / `whole_plan` findings; production `ready` snapshots block on `focused_output` / `whole_output` findings.

Production: after `plan_validated`, `tdp resume` starts the primary producer session, transitions to `production`, and records agent-selected batches via `tdp agent production apply` until every applicable item has a terminal disposition. Each apply must declare every changed snapshot-bound workspace resource path in `outputs`; incomplete evidence fails with `production_evidence_incomplete`, while unauthorized skills/guidance drift fails with `production_context_mutation_unauthorized`. Both errors leave `production.json` unchanged (artifact capture runs only after snapshot validation passes). The producer then submits a completion claim via `tdp agent production submit-completion` with `goal_met: true` and a `goal_assessment` rationale before the run advances to `whole_output_review`. Batch limits use `limits.production.max_batches` and `limits.production.max_agent_turns_per_batch`. Plan mutations are rejected during production; producers may request a controlled amendment via `tdp agent production request-amendment` (not available during whole-output review).

Plan amendment: when production exposes a material plan defect, the producer requests amendment with evidence and affected plan refs. The orchestrator pauses production (`status: paused`, `stop.code: amendment_pending`, phase `plan_amendment`), resumes the same primary planner to revise the plan, runs mandatory whole-plan review on the amended revision, reconciles production evidence against the prior plan snapshot (clearing dispositions for changed/removed items, marking overlapping batches `invalidated_by_reconciliation`, dropping related `output_evidence`, and recording `invalidated_item_ids` on the reconciliation report), then resumes the same primary producer with the reconciliation report. Output digests bind live evidence only — invalidated batches remain in the audit history but are excluded from digest and reviewer snapshots. Amendment limits use `limits.amendment.max_requests` and `limits.amendment.max_revision_cycles_per_request`. Production batches, completion claims, and blocker reports are rejected while `amendment_pending` is active. `tdp resume` routes in-flight amendments through `PlanAmendmentOrchestrator` when `pending_amendment_id` is set and the run is in `plan_amendment`, `whole_plan_review`, or `plan_validated`; production-phase resume with a pending amendment is handled inside `ProductionPhaseOrchestrator`.

Whole-output review: after production completion, `tdp resume` must enter `whole_output_review` when production modified only evidence-attributed workspace paths (authorized snapshot rebase). The engine starts a fresh reviewer session bound to the current `output_revision` and runs the mandatory gate in two repeatable modes — verification (`finding_verification`, session resume) and fresh scope review (`scope_review`, new session) — with `initial_review` as the first gate. Focused-output reviews during production do not substitute for this gate and are not auto-inserted during ordinary batches. Review packages include production traceability, an optional `rubric` on initial review only, and reviewer guidance that prioritizes output correctness and cross-artifact consistency. After `changes_requested`, the orchestrator resumes the same primary producer with instructions to use `production apply`, `evidence_revision: true`, and new evidence IDs on terminal items targeted by unresolved required findings (dispositions unchanged), then re-submit completion with `goal_met: true`. During production, focused-output evidence revision uses the same `evidence_revision` path with `focused_review_loop_id` and requires the loop `target_revision` to match the current `output_revision`. Deterministic output validation plus the acceptance invariant must pass before the orchestrator sets `outcome: accepted`. Revision cycles are capped per finding set by `limits.whole_output_review.max_revision_cycles`; scope-review rounds use `max_scope_review_rounds`. Deterministic validation failures after reviewer approval yield `blocked` on `status: completed`. Limit exhaustion pauses the run with `stop.code: limit_exhausted`. Provider transport failures pause with recoverable stop codes; unrecoverable canonical failures use `status: failed` without reopening via resume.

`tdp validate` runs deterministic plan validation and, when a completion claim or whole-output review exists, output validation as well.

## Agent CLI

```bash
tdp agent help
tdp agent readme
tdp agent schema              # list schemas; add a name to show one
tdp agent example expand-branch
tdp agent plan snapshot --run <run-id> --view active
tdp agent plan apply --run <run-id> --request request.json
tdp agent plan check --run <run-id>
tdp agent production snapshot --run <run-id> --view ready
tdp agent production apply --run <run-id> --request request.json
tdp agent production check --run <run-id>
tdp agent production request-amendment --run <run-id> --request request.json
tdp agent production submit-completion --run <run-id> --request request.json
tdp agent production report-blocked --run <run-id> --request request.json
tdp agent review request --run <run-id> --request focused-review.json
tdp agent review respond --run <run-id> --request review.json
tdp agent run status --run <run-id>
```

Production apply requires `production_revision` from the latest snapshot. `submit-completion` requires `goal_met: true` plus `goal_assessment` and records a completion claim only; the orchestrator advances to whole-output review after a valid claim and sets final `outcome` only after whole-output review. Use `evidence_revision: true` on `production apply` to revise terminal items targeted by unresolved required findings with **new** evidence IDs (dispositions unchanged): during `whole_output_review` without a loop id, or during `production` with `focused_review_loop_id` bound to the active focused-output loop (see `tdp agent example evidence-revision` and `evidence-revision-focused`).

Plan items require explicit `kind` (`work` or `aggregate`). The run seeds a root `aggregate` item; only `work` leaves appear in `ready_item_ids`. Use `update_plan` to revise plan-level metadata (`scope`, `boundaries`, `constraints`, `assumptions`, `acceptance`). Producer sessions receive `approved_plan`; production `ready` snapshots include `ready_items` with per-item contracts.

Agent plan `snapshot`/`check`/`apply` and production `snapshot` (`active`/`audit`/`ready`/`issues` for plan; `tree`/`ready` for production) share the same
plan validation contract: structured `issues` for errors, string `warnings` for
non-blocking findings, and `ok` when validation has no error-severity issues.
Production-specific batch checks use `production check`. Active plan snapshots include
`scope`, `boundaries`, and `acceptance` on each item. `plan apply` sets
`applied: true` only when the mutation batch was persisted (exit code still reflects
`ok`, not whether the batch was saved). Invalid operations and mutations that would
introduce new hard validation errors are rejected before persistence with
`operation_error`. `supersede_item` is leaf-only (no active children). Plan apply
commits plan, run digests, and events through a journaled store commit serialized by
per-run `.commit.lock` (commits and commit-managed reads).

`tdp agent plan snapshot`, `plan apply`, and `plan check` exit 0 only when
`ok` is true. `production snapshot` and `production check` follow the same rule.
A persisted `plan apply` may return `applied: true` with exit 1 only when
post-apply validation reports pre-existing error-severity issues that the mutation
did not introduce. `production apply` returns `ok: true` when the batch was
persisted; use `production snapshot` or `production check` for plan validation.

When planning dependencies, prefer the narrowest meaningful plan item as the dependency target (e.g. depend on a leaf API item rather than its parent epic) so readiness and production batching stay precise.

## Development

TDP is developed inside this monorepo and depends on the sibling [`core_tools`](../core_tools) package (`core-tools @ file:../core_tools`). Install both editable packages together; this is not published as a standalone wheel.

```bash
cd tools/top_down_planning
python -m pip install -e ../core_tools -e ".[dev]"
tdp --help
pytest                  # unit tests (default; excludes integration)
pytest -m integration   # stub-provider e2e and smoke tests
pytest -m ""            # full suite
```
