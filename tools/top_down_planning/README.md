# Top Down Planning (`tdp`)

Planning and production orchestration: receive an input and output goal, build a top-down plan, review and validate it, produce output in coherent batches, and resolve a final quality outcome.

**Runtime agents:** start with `tdp agent readme`. Packaged role skills are auto-injected (see [docs/README.md](docs/README.md)). Schemas and examples: `tdp agent schema` / `tdp agent example`.

Agent protocol: `tdp agent readme` · schemas and examples: `tdp agent schema` / `tdp agent example`

## Quickstart

```bash
cd tools/top_down_planning
python -m pip install -e ../core_tools
python -m pip install -e ".[dev]"
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
| CLI | `cli/` | User-facing (`tdp run`, `tdp resume`, `tdp doctor`, …) and agent-facing (`tdp agent …`) command wiring. |
| Config | `config/` | TDP schema (`DEFAULT_CONFIG`, allowed override paths) and `resolve_config`. |

## Provider

Provider adapters live in `core_tools.provider`. Resolved configuration selects the adapter:

```yaml
provider:
  name: cursor          # cursor | stub
  binary: /path/to/agent  # optional; otherwise agent or cursor-agent on PATH
  skip_probe: false     # skip CLI version probe when true
```

Per-role and per-activity model selection uses `agent_context.roles.<role>.model` and `agent_context.activities.<activity>.model`, each falling back through `agent_context.default.model` (resolution order: default → role → activity). `model: auto` means no explicit Cursor `--model` argument.

- `cursor` — thin Cursor CLI adapter (`--print --output-format stream-json --trust --approve-mcps --force`). `--force` is required so non-interactive turns can run shell/`tdp agent …` tools; without it those calls are rejected. Provider session ids are stored on structured session bindings under `run.sessions` (`primary_planner`, `primary_producer`) and on each review loop's `reviewer_binding`: each binding carries `session_instance_id`, `generation`, `provider_session_id`, `state`, `role`, and `kind`. The Cursor adapter registers in-memory sessions under transient `cursor-pending-*` handles until stream-json emits a durable `session_id`; orchestration persists durable ids during the provider turn (`state: bound`) as soon as the stream reports them. Transient pending handles are never passed to Cursor `--resume` (including reviewer `send()` before the first streamed turn). Cursor turns fail when the stream completes without a durable `session_id`. `limits.provider.turn_idle_timeout_seconds` (default `2`; `0` disables) ends a turn when Cursor emits no stream-json stdout for that interval (`ProviderTurnStalledError`). Missing remote sessions and idle stalls each allow **one** replacement per `phase_action_id` with a recovery manifest; lineage audit reasons are `provider_session_not_found` or `provider_turn_stalled`. Exhausted replacement marks the run `failed` with `session_recovery_exhausted`. `session_provider_id_bound` lineage events emit when a durable id is first persisted. `get_session_reference` is available on the provider for durable ref export. Agent turns run on background collector threads; every subprocess pid is tracked and killed by `terminate_all_sessions()`. Bounded reviewer sessions are released from the in-memory registry when a terminal review decision is recorded; after each phase step (including user cancel via Ctrl+C/SIGTERM), `RunEngine` tears down active sessions, emits durable cancel audit events when interrupted, and terminates tracked agent subprocesses. Later turns re-bind persisted ids through Cursor `--resume` when the in-memory adapter was torn down between phase steps.
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
| `--log-level quiet\|normal\|verbose\|trace` | from config / `normal` | Stderr verbosity only (does not change `--agent-transcript`) |
| `--log-format console\|jsonl` | from config / `console` | Human console vs JSONL on stderr |
| `--agent-text` / `--no-agent-text` | from config / on | Show thinking/response text on stderr (does not change `--agent-transcript`) |
| `--timestamps` / `--no-timestamps` | from config / off | Category prefix on the first line of each event; optional timestamp when enabled (streaming `thinking`/`response` blocks share one prefix) |
| `--agent-transcript` / `--no-agent-transcript` | from config / off | Persist redacted provider transcript |
| `--max-message-length N` | from config / unlimited | Truncate console event messages after *N* characters |
| `--max-tool-summary-length N` | from config / unlimited | Truncate `[tool:start]` / `[tool:end]` summaries after *N* characters |

Observability can be set in YAML under `observability` (same file as orchestration config). Precedence for presentation settings: built-in defaults → YAML → `--set` → explicitly supplied dedicated CLI flag (omitted flags do not override YAML). Changing `observability.*`, `notifications.*`, or `runtime.runs_dir` does not invalidate resume; `digests.config_contract` and `digests.config_execution` exclude those presentation fields.

```yaml
observability:
  # Optional; omit both for unlimited stderr output (default).
  max_message_length: 500
  max_tool_summary_length: 120
```

Provider thinking and response text is normalized from Cursor `stream-json` (`text` field or `message.content`), deduplicated when cumulative, and printed incrementally as new characters arrive. Empty thinking chunks are dropped. Explicit `\n` in agent text breaks lines within a thinking/response block; multiple sentences without newlines stay on one line until another category interrupts.

Tool invocations print as `[tool:start]` and `[tool:end]` with a concise summary from the normalized provider event (`summary` field). Cursor native tools (including shell `tdp agent …` invocations) are summarized from the nested `tool_call` payload. `tool_call` events with `subtype: started` or `completed` reach the console bridge; `tool_result` events and duplicate lifecycle events for the same `call_id` are dropped.

Console output prints `[category]` once per discrete event block (optional `[timestamp]` when `show_timestamps` is enabled). `thinking` and `response` stream incrementally with one prefix per block; explicit `\n` in agent text breaks lines within the block.

Agent session lifecycle: `[session:start]` on `planner_session_started` / `producer_session_started` / `reviewer_session_started` audit events (`phase`, `role`, `activity`, `context_digest`, `run_id`, `session_id`, `model` required); `[session:resume]` on `*_session_resumed` with the same fields; `[session:end]` on `planner_session_ended` / `producer_session_ended` / `reviewer_session_ended` audit events and from engine teardown console output for any provider session still in the in-memory registry after each blocking phase step. User cancel (Ctrl+C / SIGTERM) also records `agent_terminated` (pid, role, reason) and persists `stop.details.terminated_pids` on the pause record. Reviewer session audit events also carry `loop_id` and `review_type`; mandatory `whole_plan` / `whole_output` gates add `stage` (`initial_review`, `finding_verification`, `scope_review`). `model` is the provider-resolved CLI model label (`auto` when no explicit `--model` is passed). Console output surfaces `model` only on `[session:start]`, `[session:resume]`, and `[session:end]` (with `role`, `activity`, and other session fields). Provider session references (`get_session_reference`, `list_active_sessions`) and session lifecycle audit events carry the same label; normalized stream events do not. Run-level CLI messages use `[run:start]` and `[run:resume]`; persisted `run_created` audit events map to `[run:start]`.

**`phase` vs `stage`:** `phase` is the run lifecycle (`planning`, `whole_plan_review`, `sub_tdps`, `production`, …). `stage` is a mandatory review loop step (`initial_review`, `finding_verification`, `scope_review`) and appears on reviewer session audit events for `whole_plan` / `whole_output` gates only. Mandatory review orchestration maps to `[review:start]` (loop bootstrap) and `[review:stage]` (scope-review transition); run lifecycle transitions remain `[phase:start]` / `[phase:end]`.

`events.jsonl` remains a concise orchestration audit log (no agent prose). Capability tokens and secrets are redacted at every log level, including free-form credential forms (authorization headers, `password=` / `api_key=` assignments, and capability tokens in prose) in stderr, JSONL, `agent-transcript.jsonl`, and desktop notifications. `--log-level` and `--no-agent-text` filter stderr presentation only; `--agent-transcript` still persists its provider categories independently. Successful provider turns flush streaming `thinking`/`response` blocks so adjacent turns and session changes stay separate records. With the default unlimited `max_message_length`, a thinking/response block is held in memory until that flush; a crash before the boundary can lose the in-flight logical record. That is an accepted tradeoff for one JSONL record per logical message. Set `observability.max_message_length` and/or `observability.max_tool_summary_length` (or the matching CLI flags) to cap stderr and transcript length. Secrets are redacted before truncation.

`tdp run` and `tdp resume` trap SIGINT/SIGTERM during the engine loop: tracked agent subprocesses are terminated, orphan agents are cleaned up, `[session:cancel]` is emitted on stderr, durable cancel audit events (`agent_terminated`, `*_session_ended`) are recorded, console `[session:end]` lines are emitted for each active session, the run pauses with `stop.code: user_cancelled` and `stop.details.terminated_pids`, and the CLI exits with code 130 when the run is durably cancelled.

**Owned run interruption** (this process holds continuation ownership): Ctrl+C persists `paused` / `user_cancelled`, emits cancel observability, sends a desktop **run cancelled** notification when notifications are enabled, and exits 130. With `--stream-json`, stdout carries `{"cancelled": true, "reason": "cancelled by user", ...}` matching canonical state.

**Command interrupted without ownership** (interrupt before ownership is acquired, or after ownership was released without cancelling the run): the run record is unchanged, no run-cancel notification is sent, and `--stream-json` reports `{"cancelled": false, "command_interrupted": true, "reason": "command interrupted by user", ...}` with exit 130.

Cross-process resume ownership uses POSIX `fcntl` flock on `.resume.lock.d/.owner.lock`. Windows Python is not supported for multi-process resume locking. `CursorProvider` also fails fast on Windows with `ProviderUnsupportedPlatformError`.

Each `RunEngine.continue_run` scans for and kills orphan agents for the run before spawning provider sessions (including every `tdp resume` step and each `--until` continuation on `tdp run`). `CursorProvider` does not retry turns after cancel teardown.

## Desktop notifications

Blocking `tdp run` and `tdp resume` can send optional desktop alerts when a run reaches a milestone or needs attention. Notifications are driven by existing `events.jsonl` audit records (no orchestrator changes) plus one CLI-only outcome: partial `--until` milestones on blocking `tdp run` / `tdp resume --until …` (`target_reached`). Durable owned Ctrl+C (`user_cancelled`) surfaces as **TDP run cancelled** via the engine’s `run_paused` audit event; command-only interruption (no durable cancel) does not send a run-cancel notification. Default single-step `tdp resume` (no `--until`) does not emit `target_reached`.

Install the optional transport after editable `core_tools` is installed (see [Development](#development)):

```bash
cd tools/top_down_planning
python -m pip install -e ".[notifications]"
```

Without `notify-py`, notifications are silently skipped. `CI=true` and headless Linux environments are suppressed at send time.

Configuration lives under `notifications` (separate from `observability`). Precedence: built-in defaults → YAML → `--set` → `--no-notify` (master disable only). Omitted `--no-notify` does not override YAML/`--set`.

```yaml
notifications:
  enabled: true
  terminal: true    # run outcomes, pauses, failures
  phase: true       # major phase transitions
  progress: false   # per-batch / per-item (noisy)
```

```bash
tdp run --config kanban.yaml --set notifications.progress=true
tdp resume --run <run-id> --no-notify
```

| Tier | Default | Examples |
| --- | --- | --- |
| `terminal` | on | `outcome_resolved`, `run_failed`, `run_paused` (limit/operational pauses), `*_failed` outcome events. Ctrl+C (`user_cancelled`) and partial `--until` milestones notify whenever `notifications.enabled` is true, even if `terminal` is false. |
| `phase` | on | `whole_plan_review_started`, `production_phase_started`, `production_completed` |
| `progress` | off | `production_batch_recorded`, `focused_review_approved`, `planning_candidate_ready` |

`validate`, `status`, `inspect`, `doctor`, `tdp agent *`, and `tdp resume --check` never notify. Changing `notifications.*` does not invalidate resume (presentation tier, like `observability.*`).

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
tdp doctor --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp resume --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp prepare --config tools/top_down_planning/examples/top-down-planning.yaml --output .tdp/execution
tdp execute --manifest .tdp/execution/manifest.json
tdp sub-tdp attach --parent <parent-run-id> --child <child-run-id> --runs-dir <runs-root>
```

Configuration precedence: built-in defaults → YAML file → repeated `--set path=value` overrides → dedicated CLI flags when explicitly supplied. Unknown paths in YAML or `--set` are rejected. Resolved configuration is materialized to `<runs-root>/<run-id>/resolved-config.yaml`. Resume binds approvals to `digests.config_contract` and limit changes to `digests.config_execution`; both exclude `observability`, `notifications`, and `runtime.runs_dir`. Contract changes on resume require `--allow-config-drift` (before whole-plan approval they apply; after approval they are ignored with warnings). CLI invocation metadata is persisted separately in `invocation.json`.

### Path resolution

Config files may live anywhere. `project.workspace` is the canonical workspace root for a run.

- `project.workspace` resolves against the **process working directory** (defaults to process cwd when omitted).
- `run.input_refs`, `run.output_goal_file`, and all `agent_context.default`, `agent_context.roles.*`, and `agent_context.activities.*` resource / skill / guidance file entries resolve against the resolved `project.workspace`.
- `runtime.runs_dir` resolves against the process working directory.

Absolute paths are used directly. Launch `tdp` from the intended working directory (for example the repository root).

### Prepared Sub-TDP execution (prepare → execute)

Plan once, materialize an immutable execution package, then run parent or unit execution without re-planning:

```bash
tdp prepare --config <project.yaml> --output .tdp/execution
tdp execute --manifest .tdp/execution/manifest.json --runs-dir <runs-root>
tdp execute --manifest .tdp/execution/manifest.json --parent-only --runs-dir <runs-root>
tdp execute --manifest .tdp/execution/manifest.json --unit <unit-id> --runs-dir <runs-root>
tdp sub-tdp attach --parent <parent-run-id> --child <child-run-id> --runs-dir <runs-root>
tdp resume --run <parent-run-id> --runs-dir <runs-root>
```

The package entry point is `manifest.json` (parent and unit plan snapshots, digests, dependency graph, embedded execution config, and inherited plan approval). `tdp execute --manifest` must reference that exact filename. Persisted package IDs are immutable: the run store rejects a second package with the same `package_id` and a different digest. `tdp execute` loads semantic config from the package — it does not require `cwd/config.yaml`. Optional `--config` / presentation `--set` overrides are limited to observability, notifications, and run-store location. Prepared children load the full assigned subtree and inherited context; they do not enter planning. Direct `tdp execute --unit` and parent-driven execution share `PreparedUnitExecutor` and the same run-specific provider runtime wiring.

Parent lifecycle for prepared execution:

```text
sub_tdps (drive or attach children)
→ all children accepted
→ synthesize child results (completion_claim status=integration_pending, goal_met=false)
→ parent production (integration producer)
→ submit-completion with goal_met=true
→ whole_output_review
→ acceptance
```

`--parent-only` creates the parent, enters `sub_tdps`, and **pauses** (`stop.code=sub_tdps_awaiting_children`) so independently executed units can be attached. After every unit is attached, resume the parent with `tdp resume --run <parent-run-id>` to continue synthesis, integration production, and whole-output review. Attach requires parent `phase=sub_tdps` **and** `status=paused`, holds parent run ownership for the full validate-and-commit path, and accepts only a completed/accepted child with whole-output approval bound on the child run. Dependencies must already be attached with matching `accepted_result_digest` values before a dependent unit can attach. The child's embedded `unit_id` is authoritative.

Direct unit execution (`tdp execute --unit`) with dependencies requires an explicit complete `--upstream dep=<child-run-id>` map; each upstream run must belong to the mapped dependency unit and pass accepted-delivery validation. Unrelated accepted siblings that changed shared workspace resources can be included with `--baseline <accepted-run-id>` (repeatable) without becoming semantic dependencies. Child creation authorizes configured **resource** snapshot drift from the cumulative workspace baseline using **content-bound** `accepted_result.workspace_changes` (current workspace sha256 must match the merged final write digest; same-path overwrites require snapshot-lineage succession rooted at the package initial context snapshot; composite multi-result `--baseline` joins merge workspace lineage from all baseline wrappers; unrelated conflicting hashes fail closed). Guidance and skill drift are always rejected. Parent resume similarly authorizes attached accepted-child closure using the package initial context snapshot as the succession root (including parent integration evidence when present) before synthesis. Child package bindings are immutable after execution starts (retrofit only while `plan_validated` with no batches/sessions). Accepted-child delivery validation recomputes the live production output digest and requires `completed` / `output_validated` / `accepted`. Terminal children are revalidated before reuse. Package IDs are validated as store IDs and confined under `.execution_packages/`. Resuming a parent after a permanently failed Sub-TDP unit fails the parent (`sub_tdp_unit_permanently_failed`) rather than leaving it `running`.

Child runs bind direct semantic dependencies as digest-verified wrappers (`accepted_result`, `accepted_result_digest`, `upstream_contract_digest`) and persist `workspace_baseline_accepted_results` for context authorization. Accepted-result attestations include content-bound `workspace_changes` (latest live-batch capture per path), baseline/final context snapshot digests, and batch delivery (`batches[].result.outputs`, `batches[].result.contributions`). Wrapper delivery is revalidated per child; workspace bytes are checked once against the merged baseline map (not per historical wrapper). Parent resume, WOR entry, production completion, child create, and baseline closure re-load child production and require the stored attestation to match a live `accepted_result_record` re-derivation; bare `output_refs` path lists never authorize. The live output digest must match `run.digests.output`.

Authoritative Sub-TDP orchestration lives in parent `production.json` → `sub_tdps` (journaled via `RunStore.commit`). Do not hand-edit orchestration state.

Use either `run.output_goal` (inline text) or `run.output_goal_file` (path to a UTF-8 file), not both. File-backed goals resolve against `project.workspace`. At run start the file contents are loaded into `plan.output_goal`; the path stays in resolved config. Resume re-reads the file and rejects digest mismatches when the content changed unless `--allow-config-drift` is set (before whole-plan approval).

### Run contracts and agent context

Each field has one responsibility:

```text
run.input_refs
    Authoritative problem and specification inputs.

run.output_goal / run.output_goal_file
    Authoritative deliverable contract.

agent_context.default
    Shared supporting context inherited by every role and activity (model, guidance,
    resources, skills).

agent_context.roles.<role>
    Role-wide overlays (planner, producer, reviewer). Each role section may override
    the shared model and add guidance, resources, and skills on top of default.

agent_context.activities.<activity>
  Activity-specific overlays. Orchestrator activities: initial_plan, plan_revision,
  plan_amendment, production, output_revision, initial_review, finding_verification,
  scope_review. Effective context merges default → role → activity. Session resume
  requires the same role, activity, and context_digest; activity changes always start
  a fresh provider session.

project.workspace
    Canonical workspace root.
```

`run.input_refs` and the resolved output goal are supplied automatically to planner, producer, and reviewer sessions. Do not repeat them under `agent_context.roles.*` or `agent_context.activities.*`.

Use guidance for role or activity behavior preferences. Use `run.input_refs`, boundaries, acceptance, and output_goal for authoritative work contracts. Use resources for supporting reference material and skills for reusable methods.

Guidance is additive with `agent_context.default`, attached to fresh agent sessions, and included in the supporting-context digest. It does not change run acceptance, create runtime enforcement, or introduce new lifecycle transitions. Each guidance entry is exactly one of `{text: ...}` or `{file: ...}`.

`--set agent_context.roles.<role>.guidance=…` and `--set agent_context.activities.<activity>.guidance=…` must be JSON arrays of objects (the `--set` parser does not accept YAML mapping syntax inside list items). Use double quotes and escaped JSON, for example:

```bash
tdp run --config config.yaml \
  --set 'agent_context.roles.producer.guidance=[{"text":"Work in coherent batches."},{"file":"docs/producer-guidance.md"}]'
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

  roles:
    planner:
      model: reasoning-model
      resources:
        - docs/planning-guidelines.md

    producer:
      model: coding-model
      guidance:
        - text: >
            Work in coherent batches. Consider focused review and useful
            Git checkpoints; skip a commit when that is better judgment.

    reviewer:
      model: review-model

  activities:
    initial_plan:
      model: reasoning-model
    production:
      model: coding-model
    initial_review:
      model: review-model
```

Flat `agent_context.planner` / `producer` / `reviewer` keys are rejected; recreate runs after migrating to the nested shape above.

Packaged TDP agent skills (`bundled_skills/tdp-agent/`) are auto-injected for every role when `agent_context.bundled_skills` is true (the default). Add extra project skills under `agent_context.roles.*.skills` or `agent_context.activities.*.skills` as needed.

Role and activity `guidance`, `resources`, and configured `skills` are additive with `agent_context.default`. Skills are path-only bundles: a file path or a directory containing `SKILL.md`. Effective context is attached to fresh planner, producer, and reviewer sessions per orchestrator activity.

Run contracts bind via `digests.input` and `digests.output_goal` at run creation. Supporting agent context uses a **spec vs snapshot** split:

- `digests.context_spec` — stable declarations (default, role, and activity models; guidance entries; resource path selection; skill declarations including packaged `tdp:builtin:` keys) plus the resolved snapshot exclusion policy (`context_snapshot.excludes` and built-in policy version).
- `digests.context_snapshot` — materialized resource file bytes, skill contents, and guidance text/file digests, persisted in `context_snapshot_binding` on the run record.

Resume validates non-model `context_spec` fields strictly (guidance/resource/skill declarations and snapshot exclusion policy). Model-only `context_spec` drift is allowed before whole-plan approval when `--allow-config-drift` is set and updates `digests.context_spec` on apply. `context_snapshot` is skipped only during the `production` phase so in-flight authorized mutations are allowed. Each `production apply` validates cumulative snapshot drift against the candidate batch (proposed output refs before capture plus hash-matched prior evidence) and rejects incomplete evidence before persistence. Production completion re-validates with hash-matched evidence only (latest capture per path must match current workspace bytes), rebases `context_snapshot` when authorized, emits `context_snapshot_rebased` after the run record is persisted, then enters `whole_output_review`. Whole-output and focused-output owner revisions that change resources rebase `context_snapshot` and `digests.output` atomically when the owner turn closes. Unauthorized workspace changes block apply retry or completion and later phase entry.

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

List-shaped `{path, digest}` entries, absolute path keys, and a binding-level `workspace` field are rejected; recreate the run. Config document `version` is unrelated to run-record `schema_version` (currently `3`). Unsupported or missing run `schema_version` fails load with a recreate message — there is no automatic migrator. Prefer snapshot excludes over

Snapshot excludes apply only to **context snapshot** resource materialization (`SnapshotPolicy.collect`). Agent session resource manifests still expand directories recursively and may list `__pycache__` / `.pyc` paths from `resolve_expanded_path_list`; that packaging surface is intentionally unchanged — use snapshot excludes for integrity binding, not for agent manifest hygiene.

Phase-entry audit events distinguish precondition failures from orchestrator start:

- `phase_entry_attempted` — engine iteration selected a phase and began resume precondition checks.
- `phase_entry_blocked` — precondition validation rejected entry (`error_code`, optional `digest_kind`, shortened `expected_digest` / `actual_digest`).
- `whole_*_review_started` / `*_scope_review_started` / `*_scope_review_changes_requested` — mandatory review loop started, scope-review stage entered, or scope-review findings reopened (console: `[review:start]`, `[review:stage]`, or `[review]` respectively). Concise review audit companions include `review_findings_reported`, `review_revision_required`, `review_incomplete`, `review_advisory_handoff_started`, `review_finding_action_recorded`, and `review_challenge_submitted`.

`[session:end]` maps from durable `planner_session_ended`, `producer_session_ended`, and `reviewer_session_ended` audit events (see Console observability above), plus engine teardown console output after each phase step.

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

When the orchestrator starts a provider session, it exports `TDP_RUNS_DIR`, `TDP_RUN_ID`, `TDP_AGENT_REQUESTS_DIR`, and `TDP_CAPABILITY_TOKEN_FILE` (path to the current session capability token) to provider subprocesses **before** any turn where the agent may run mutating `tdp agent …` commands. Write mutating request payloads only under `$TDP_AGENT_REQUESTS_DIR` (the run's `agent-requests/` directory). Reviewer sessions start with the bounded review package in a single provider turn (`begin_reviewer_review`); follow-up turns on the same session use `deliver_reviewer_turn` (`send` + capability bind). Mutating commands require the capability token; authorization is bound to run phase, role, provider session, and (for reviewers) review loop — not a self-declared `--role` flag. Capability records store only a hash of the secret; tokens are revoked when turns, loops, or phases end.

Planner, producer, and reviewer packages include `protocol_instructions` (a rendered Markdown string from package-owned Jinja templates under `src/top_down_planning/prompts/templates/`) and `tool_instructions` (`tdp agent` command templates). Edit templates and `prompts/contexts.py` for role protocol behavior; do not add inline protocol prose in orchestrator session modules. The provider adapter surfaces `protocol_instructions` at the top of the prompt so agents do not substitute host IDE planning artifacts for persisted `tdp agent` mutations.

Agents mutate run state only through `tdp agent …` shell commands (which persist to the run store). The orchestrator does not intercept provider tool events for plan/production/review mutations. After each provider turn it observes store changes (pending focused reviews, persisted production batches, completion claims, review decisions) and resolves phase completion from explicit signal tokens (`candidate_plan_ready`, `amendment_revision_ready`, etc.) in assistant text or `done.signal` metadata. Producer batch turns close when `production apply` persists a batch; completion turns close when `submit-completion` persists a valid completion claim.

`tdp run` supports `--until plan|validated|completed` (default `plan`). `tdp resume` advances one phase step by default, or loops to `--until` when set. Both use the central `RunEngine` continuation loop.

`tdp resume --check` builds and prints the same structured resume plan summary as apply mode without mutating the run, saving config, appending events, or contacting the provider. Use `--config` and/or repeatable `--set path=value` to evaluate limit changes (increase or decrease when above consumed usage, or when consumption is untracked); diagnostics include consumed usage, stored limit, candidate limit, and remaining budget for exhausted limits. Pass `--allow-config-drift` to opt in to contract and model config changes: before whole-plan approval they apply (with warnings) and rebind `digests.config_contract`, `digests.input`, `digests.output_goal`, and `digests.context_spec` when applicable; model-only `context_spec` drift is accepted without changing non-model declarations. After approval, approval-bound contract and model changes are listed as ignored and do not take effect. Non-model `context_spec` drift (guidance paths, resources, skills, exclusion policy) still blocks resume. Provider, workspace, plan, and evidence integrity checks remain strict even with the flag. Interrupt taxonomy: Ctrl+C or SIGTERM pauses the run with `stop.code: user_cancelled`, terminates tracked and orphan agent subprocesses, and records `stop.details.terminated_pids`; `RunEngine.continue_run` scans for and kills orphan agents before spawning provider sessions. Idle `running` runs (no live orchestrator, no orphan agents) continue via `running→running` resume; interrupted runs with orphan agents are reconciled to `paused` with `stop.code: orchestrator_interrupted` (`tdp doctor --fix` forces reconciliation). `tdp doctor` reports workspace hygiene (idle vs interrupted running runs, incomplete dirs, staging leftovers) and per-run orphan pids. `tdp run --force` overrides the refusal to start when interrupted runs still have orphan agents in the workspace.

Persistence uses journaled `RunStore.commit()` for multi-file mutations: staged writes, per-file digests and backups, journal records replacements only after successful `Path.replace()`, digest-verified recovery, per-run `.commit.lock` serialization around commits and commit-managed reads (`load_run`, `load_plan`, `load_production`, `load_events`, `load_review`, `list_reviews`), and rollback or completion of pending event appends after a crash. Each run directory includes `invocation.json` (latest CLI invocation metadata, not part of semantic config digests). Output evidence records bind artifact content (`sha256`, `size`, `media_type`, `captured_at`) and snapshot approved files under immutable UUID paths in the run store. Evidence IDs are unique across the full run history.

`tdp run` creates the run store and drives the run until the requested milestone or a limit/failure. On the default `plan` target, success means phase `whole_plan_review`. `tdp resume` validates digests and session references before continuing.

Whole-plan review: the orchestrator starts a reviewer session with the bounded review package (`begin_reviewer_review`), binds capability, and consumes the review turn. Each successful `review respond` closes the current reviewer turn: the orchestrator aborts the in-flight provider turn when the decision is persisted, waits for the session collector to settle, then releases the bounded reviewer session (`reviewer_session_ended`) before owner revision or the next gate. Owner advisory turns close when `review record-actions` persists. A turn that ends without `review respond` queues another reviewer turn with a nudge (bounded by `limits.review.max_agent_turns_per_gate`) before pausing with `limit_exhausted`. A background poll also watches for persisted review decisions while the turn is open so a stalled agent subprocess cannot block progress after respond. Each reviewer turn persists a bound durable `reviewer_binding` during the provider stream before recheck can resume the same session. Mandatory gates use two repeatable modes — verification (`finding_verification`, session resume) and fresh scope review (`scope_review`, new session) — with `initial_review` as the first discovery gate. The typical clear path runs initial discovery, then fresh scope discovery — two `reviewer_session_started` events, two `reviewer_session_ended` events, and zero `reviewer_session_resumed`. Revision paths emit `reviewer_session_resumed` for verification rechecks before starting a fresh scope-review session. When resume session policy clears a lost transient binding after planner revision work is already recorded, verification recheck starts a replacement reviewer session with the recheck package instead of resuming. There is no hard cap of two total review executions; `limits.whole_plan_review.max_revision_cycles` and `max_scope_review_rounds` bound verification and scope-review rounds independently. Clear initial approval still requires a separate fresh `scope_review` — finding closure alone is not final approval. Whole-plan discovery and scope review use contract v2 with `audit_attestation`, `finding_families`, and structured `analysis_context.validation_issues` (`tdp agent example review-respond-family-discovery`, `review-respond-family-verification`, `review-respond-scope`). Owner revisions record `family_fix` sweeps via `tdp agent review record-actions`. Each loop binds findings to the current plan revision, resumes the same primary planner for revisions after `changes_requested`, and requires verification recheck (`finding_verification` delivery) before scope review when findings were raised. Review packages include `review_policy.category_definitions`, `rubric_items`, `required_audit_passes`, and optional configured rubric themes on initial review; use `tdp agent readme` (Audit attestation; Built-in finding-family rule_id values) and stage examples for `review respond` payloads — not TDP source. Reviewer protocol and stage guidance prioritize plan correctness and internal consistency. Review responses and audit events expose `revise_at` plus required/optional finding counts and ids. Contract-v1 review records are not supported; recreate runs that predate mandatory whole-plan contract v2. After the gate completes, deterministic `validate_plan(..., mode="approval")` must pass before the run advances to `plan_validated`. Limit exhaustion pauses the run with `stop.code: limit_exhausted` (`stop.details` carries the full `limits.whole_plan_review.max_*` path, `loop_id`, and `exhausted_budget`). Resume with an increased limit revives the same review loop and preserves `revision_cycles` / `scope_review_rounds` — it does not open a new loop or reset the phase budget.

Focused reviews: during `planning` or `production`, the primary planner or producer may request optional `focused_plan` or `focused_output` reviews via `tdp agent review request` with bounded `scope.item_ids`. Each request starts a fresh reviewer session; the same reviewer rechecks within the loop. Reviewer turns close on persisted `review respond` decisions with the same abort/poll behavior as mandatory gates, including gate-turn auto-retry bounded by `limits.review.max_agent_turns_per_gate`. Focused approval does not substitute for mandatory whole-plan or whole-output gates. Discovery may use flat `target_refs`, structured `instance_ref`, or optional `finding_families` within scope (`review-respond`, `review-respond-focused-with-instance-ref`, `review-respond-family-discovery-focused-plan`, `review-respond-family-discovery-focused-output`). Limits use `review.focused_plan.enabled`, `review.focused_output.enabled`, and `limits.focused_plan_review` / `limits.focused_output_review`. Unresolved required findings in an active focused loop block `candidate_plan_ready`, `production_apply`, and `submit-completion` for overlapping items. Plan `ready` snapshots block on `focused_plan` / `whole_plan` findings; production `ready` snapshots block on `focused_output` / `whole_output` findings.

Production: after `plan_validated`, `tdp resume` starts the primary producer session, transitions to `production`, and records agent-selected batches via `tdp agent production apply` until every applicable item has a terminal disposition. For prepared parent execution (`tdp execute` without `--unit`), the engine enters `sub_tdps` instead: dependency-ordered child runs via `PreparedUnitExecutor` (or attach of independently executed children), parent synthesis with `integration_pending`, then a parent **integration** `production` turn that must submit `goal_met=true` before `whole_output_review`. Each successful `production apply` closes the current producer turn (one batch per turn): the orchestrator aborts the in-flight provider turn when a batch is persisted, waits for the session collector to settle, then immediately queues the next producer turn on the same session when more batches are allowed. A background poll also watches for persisted batches while the turn is open so a stalled agent subprocess cannot block progress after apply. A completion-only turn closes when `submit-completion` persists a valid completion claim with the same abort/poll behavior. Provider session concurrency failures pause the run with `stop.code: provider_turn_failed` instead of marking it `failed`. Each apply must declare every changed snapshot-bound workspace resource path in `outputs`; incomplete evidence fails with `production_evidence_incomplete`, while unauthorized skills/guidance drift fails with `production_context_mutation_unauthorized`. Both errors leave `production.json` unchanged (artifact capture runs only after snapshot validation passes). The producer then submits a completion claim via `tdp agent production submit-completion` with `goal_assessment` before the run advances to `whole_output_review`. Batch limits use `limits.production.max_batches` and `limits.production.max_agent_turns_per_batch`. Plan mutations are rejected during production; producers may request a controlled amendment via `tdp agent production request-amendment` (not available during whole-output review).

Plan amendment: when production exposes a material plan defect, the producer requests amendment with evidence and affected plan refs. The orchestrator pauses production (`status: paused`, `stop.code: amendment_pending`, phase `plan_amendment`), resumes the same primary planner to revise the plan, runs mandatory whole-plan review on the amended revision, reconciles production evidence against the prior plan snapshot (clearing dispositions for changed/removed items, marking overlapping batches `invalidated_by_reconciliation`, dropping related `output_evidence`, and recording `invalidated_item_ids` on the reconciliation report), then resumes the same primary producer with the reconciliation report. Output digests bind live evidence only — invalidated batches remain in the audit history but are excluded from digest and reviewer snapshots. Amendment limits use `limits.amendment.max_requests` and `limits.amendment.max_revision_cycles_per_request`. Production batches, completion claims, and blocker reports are rejected while `amendment_pending` is active. `tdp resume` routes in-flight amendments through `PlanAmendmentOrchestrator` when `pending_amendment_id` is set and the run is in `plan_amendment`, `whole_plan_review`, or `plan_validated`; production-phase resume with a pending amendment is handled inside `ProductionPhaseOrchestrator`.

Whole-output review: after production completion, `tdp resume` must enter `whole_output_review` when production modified only hash-matched evidence-attributed workspace paths (authorized snapshot rebase). The engine starts a fresh reviewer session bound to the current `output_revision` and runs the mandatory contract-v2 gate (finding families, audit attestation, producer owner family sweeps) in two repeatable modes — verification (`finding_verification`, session resume) and fresh scope review (`scope_review`, new session) — with `initial_review` as the first gate. Each successful `review respond` closes the current reviewer turn the same way as whole-plan review (abort in-flight provider turn, settle collector, `reviewer_session_ended`, gate-turn auto-retry on missing respond, background poll while the turn is open). See `tdp agent example review-respond-family-discovery-output`, `review-respond-family-verification-output`, and `review-record-family-fix-output`. Focused-output reviews during production do not substitute for this gate and are not auto-inserted during ordinary batches. Review packages include `review_policy.category_definitions`, production traceability, stable `rubric_items`, `required_audit_passes`, and reviewer guidance that prioritizes output correctness and cross-artifact consistency. After `changes_requested`, the orchestrator resumes the same primary producer with instructions to use `production apply`, `evidence_revision: true`, and new evidence IDs on terminal items targeted by unresolved required findings (dispositions unchanged), record owner `family_fix` sweeps via `tdp agent review record-actions`, then re-submit completion with `goal_assessment`. The owner revision turn closes when the new completion claim persists; the orchestrator then atomically refreshes `digests.output` and rebases `context_snapshot` when resource evidence changed. Stop immediately afterward. During production, focused-output evidence revision uses the same `evidence_revision` path with `focused_review_loop_id` and requires the loop `target_revision` to match the current `output_revision`; owner turns likewise rebase the context snapshot when resources change. Contract-v1 review records are not supported; recreate runs that predate mandatory whole-output contract v2. Deterministic output validation plus the acceptance invariant must pass before the orchestrator sets `outcome: accepted`. Revision cycles are capped per finding set by `limits.whole_output_review.max_revision_cycles`; scope-review rounds use `max_scope_review_rounds`. Deterministic validation failures after reviewer approval yield `blocked` on `status: completed`. Limit exhaustion pauses the run with `stop.code: limit_exhausted` (`stop.details` carries the full `limits.whole_output_review.max_*` path, `loop_id`, and `exhausted_budget`). Resume with an increased limit revives the same review loop and preserves `revision_cycles` / `scope_review_rounds` — it does not open a new loop or reset the phase budget. Provider transport failures pause with recoverable stop codes; unrecoverable canonical failures use `status: failed` without reopening via resume.

`tdp validate` runs deterministic plan validation and, when a completion claim or whole-output review exists, output validation as well.

## Agent CLI

```bash
tdp agent help
tdp agent readme
tdp agent schema              # list schemas; add a name to show one
tdp agent example expand-branch
tdp agent plan snapshot --run <run-id> --view active
tdp agent plan apply --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/plan-apply-r0-a01.json
tdp agent plan check --run <run-id>
tdp agent production snapshot --run <run-id> --view ready
tdp agent production apply --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-apply-batch-01-a01.json
tdp agent production check --run <run-id>
tdp agent production request-amendment --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-amendment-a01.json
tdp agent production submit-completion --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-completion-a01.json
tdp agent production report-blocked --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-blocked-a01.json
tdp agent review request --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/review-request-focused-a01.json
tdp agent review respond --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/review-respond-scope-r0-a01.json
tdp agent run status --run <run-id>
```

Production apply requires `production_revision` from the latest snapshot. `submit-completion` requires `goal_assessment` and records a completion claim only; the orchestrator advances to whole-output review after a valid claim and sets final `outcome` only after whole-output review. Use `evidence_revision: true` on `production apply` to revise terminal items targeted by unresolved required findings with **new** evidence IDs (dispositions unchanged): during `whole_output_review` without a loop id, or during `production` with `focused_review_loop_id` bound to the active focused-output loop (see `tdp agent example evidence-revision` and `evidence-revision-focused`).

Plan items require explicit `kind` (`work` or `aggregate`). The run seeds a root `aggregate` item (`item-root`, title `Root`); only `work` leaves appear in `ready_item_ids`. Before adding children under `item-root`, use `update_item` to set a meaningful title and outcome. Use `update_plan` for plan-level metadata (`scope`, `boundaries`, `constraints`, `assumptions`, `acceptance`, `risks`). Once `item-root` has active children, plan validation errors on `default_root_title` or `missing_root_outcome`. Item-level `risks` and `source_refs` (always present; populate for requirement traceability when needed) use `add_item` / `update_item`. Every `work` leaf must set item-level `scope.includes`, `scope.excludes`, and/or `boundaries`; draft validation warns and approval mode errors when all three are empty on a work leaf.

Producer sessions receive `approved_plan`; production `ready` snapshots include `ready_items`. Both use the same canonical item contract: `id`, `title`, `outcome`, `kind`, item-owned `scope`/`boundaries`, merged `effective_scope`/`effective_boundaries`, `acceptance`, `risks`, `source_refs`, and `depends_on` (`ready_items` also include `ancestor_path`). Producers enforce batch boundaries from `effective_*`; approved work leaves must already have item-level scope or boundaries. Plans carry `schema_version` `2`; unsupported or missing plan `schema_version` fails load with a recreate message — there is no plan migrator.

Agent plan `snapshot`/`check`/`apply` and production `snapshot` (`active`/`audit`/`ready`/`issues`/`budget` for plan; `tree`/`ready`/`dispositions` for production) share the same
plan validation contract: structured `issues` for errors, string `warnings` for
non-blocking findings, and `ok` when validation has no error-severity issues.
Production-specific batch checks use `production check`. Active plan snapshots include
item-owned `scope`, `boundaries`, `acceptance`, `risks`, and `source_refs`. Production
`ready` snapshots and `approved_plan.items` add merged `effective_scope` and
`effective_boundaries`. `plan apply` sets
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

TDP is developed inside this monorepo and depends on the sibling [`core_tools`](../core_tools) package (`core-tools @ file:../core_tools`). **Supported installation is monorepo editable only** — install both packages from `tools/top_down_planning`:

```bash
cd tools/top_down_planning
python -m pip install -e ../core_tools
python -m pip install -e ".[dev]"
```

Install `core_tools` before TDP: pip cannot resolve `file:../core_tools` when both packages are passed in one combined `pip install -e … -e …` on a fresh environment.

This is not published as a standalone wheel. The `file:../core_tools` dependency is location-dependent; a built wheel is used only for **packaging verification** in CI (template, skill, and import smoke against the assembled artifact). Do not install the wheel outside the monorepo layout expecting portable dependency resolution.

```bash
tdp --help
python -m pytest                  # parallel unit tests (excludes integration and packaging)
python -m pytest -n 0             # serial unit tests for debugging
python -m pytest -m integration   # stub-provider e2e; no wheelhouse required
python -m pytest -o addopts='' tests  # review-plan full suite (builds a wheelhouse if unset)
export TDP_PACKAGING_WHEELHOUSE=$(python scripts/build_packaging_wheelhouse.py)
python -m pytest -m packaging     # offline install smoke using a pre-built wheelhouse
```
