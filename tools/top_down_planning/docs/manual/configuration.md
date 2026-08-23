# Configuration

**Audience:** operators setting and overriding TDP configuration.

Unknown keys in YAML or `--set` are rejected. Resolved configuration is written to `<runs-root>/<run-id>/resolved-config.yaml`. Invocation metadata is persisted separately in `invocation.json`. Digest internals: [config and snapshots](../internals/config-and-snapshots.md).

Inspect the published config schema with `tdp agent schema config`.

## Precedence

| Tier | Semantic orchestration (`planning.*`, `limits.*`, `agent_context.*`, `run.*`, `provider.*`, …) | Presentation (`observability.*`, `notifications.*`, `runtime.runs_dir`) |
| --- | --- | --- |
| 1 | Built-in defaults | Built-in defaults |
| 2 | YAML `--config` | YAML `--config` |
| 3 | Repeatable `--set path=value` | Repeatable `--set path=value` |
| 4 | (no dedicated semantic flags) | Explicit dedicated CLI flag (`--log-level`, `--no-notify`, `--runs-dir`, …). **Omitted flags do not override YAML/`--set`.** |

`--set` is on `tdp run`, `tdp resume`, `tdp prepare`, and `tdp execute`. `tdp execute` does not reload semantic YAML from cwd; optional `--config` / `--set` there (and `tdp prepare --planning-run`) are limited to presentation and run-store location. A config-backed `tdp prepare` accepts semantic `--set` like `tdp run`.

## Path resolution

Config files may live anywhere. Launch `tdp` from the intended working directory.

- `project.workspace` resolves against the **process working directory** (defaults to cwd when omitted).
- `run.input_refs`, `run.output_goal_file`, and `agent_context` resource / skill / guidance **file** entries resolve against resolved `project.workspace`.
- `runtime.runs_dir` resolves against the process working directory.

Absolute paths are used directly. See [install](install.md) for working-directory instructions.

## Run contracts

| Field | Responsibility |
| --- | --- |
| `run.input_refs` | Authoritative problem and specification inputs |
| `run.output_goal` or `run.output_goal_file` | Authoritative deliverable contract (mutually exclusive) |
| `run.boundaries` / `run.acceptance` | Plan-level guardrails merged into item `effective_*` contracts |
| `project.workspace` | Canonical workspace root |

Do not repeat `run.input_refs` or the output-goal file under `agent_context` resources. File-backed goals are loaded into `plan.output_goal` at run start; resume re-reads the file and rejects digest mismatches unless `--allow-config-drift` applies before whole-plan approval.

## Role and activity overlays

Effective context merges **default → role → activity**.

- `agent_context.default` — shared model, guidance, resources, skills
- `agent_context.roles.<planner|producer|reviewer>`
- `agent_context.activities.*` — `initial_plan`, `plan_revision`, `plan_amendment`, `production`, `output_revision`, `initial_review`, `finding_verification`, `scope_review`

`agent_context.bundled_skills` defaults to `true` (packaged TDP agent skills). Extra project skills are path-only (file or directory containing `SKILL.md`). Guidance entries are exactly `{text: ...}` or `{file: ...}`. Flat `agent_context.planner` keys are rejected.

`--set` for guidance lists must be JSON arrays, not YAML mappings inside the value.

## Models

`agent_context.*.model` with fallback default → role → activity. `model: auto` means no explicit Cursor `--model`.

## Snapshot exclusions

`context_snapshot.excludes` (default-on when the section is omitted):

```yaml
context_snapshot:
  excludes:
    defaults: true   # built-ins include __pycache__, *.py[cod], common tool caches
    patterns: []     # gitignore/gitwildmatch order; .gitignore is not inherited
```

Empty `patterns` does not disable built-ins; set `defaults: false` to turn them off. Exclusion policy is part of `context_spec` identity. Exclusions apply to **resource** snapshot materialization, not to skills or guidance.

## Reviews

`review.focused_plan.enabled` and `review.focused_output.enabled` default true. `review.whole_plan.rubric` and `review.whole_output.rubric` are inspection themes for mandatory gates. `review.revise_at` overlays exist at whole and focused levels (see schema). Changing review policy is contract-tier for resume.

## Limits

Under `limits.*` (execution digest). Package defaults include planning item/turn caps, focused and whole review revision cycles, production batch/turn caps, amendment caps, `limits.review.max_agent_turns_per_gate`, and `limits.provider.max_retries_per_call` / `turn_idle_timeout_seconds` (default `2`; `0` disables idle stall detection) / `max_stream_json_record_bytes` (default `1048576` / 1 MiB; assembled Cursor stream-json line cap, including the terminating newline; TDP requires an integer >= 1). Exact paths: `tdp agent schema config` or the example YAML [limits block](../../examples/top-down-planning.yaml).

## Observability and notifications

See [observability](observability.md). These sections are presentation: changing them does not invalidate resume.

## Provider

```yaml
provider:
  name: cursor    # default; stub is test-only
```

Optional `binary`, `skip_probe`. Details: [install](install.md).

## Runtime paths

`runtime.runs_dir` — run store root, resolved from process cwd. Required for `tdp run` / `prepare` / `execute` via `--runs-dir`, `$TDP_RUNS_DIR`, or this field (no `./runs` fallback on those commands).

## Execution mode

`execution.mode` defaults to `single`. Prepared parent/child execution is a separate operator path (`tdp prepare` / `tdp execute`); see [prepared execution](../workflows/prepared-and-sub-tdp.md).

## Resume and drift

Resume matches stored approval records against current run digests. Plan approval and whole-output approval use **different key sets** (`domain/approval_digests.py`, checked in `prepare_resume._approval_binding_valid`):

| Approval | Digest keys that must match |
| --- | --- |
| Whole-plan (`PLAN_APPROVAL_DIGEST_KEYS`) | `plan`, `config_contract`, `input`, `output_goal`, `context_spec` |
| Whole-output, when present and approved (`OUTPUT_APPROVAL_DIGEST_KEYS`) | the plan keys plus `output` and `context_snapshot` |

A pending `whole_output` loop (no current approved output record) skips the `output` and `context_snapshot` checks. Resume must **not** demand those keys on the **plan** approval. Limit changes bind to `digests.config_execution`. Both contract and execution projections exclude `observability`, `notifications`, and `runtime.runs_dir`.

By default, resume rejects contract drift and non-model `context_spec` drift (guidance/resources/skills/exclusion policy) and provider/workspace changes. `--allow-config-drift`:

- **Before** whole-plan approval: accepted contract and model changes apply and rebind digests. Model-only `context_spec` drift is accepted; other `context_spec` fields still block.
- **After** whole-plan approval: approval-bound contract and model changes are ignored with warnings; limit and presentation changes still apply.

Limit-only changes update `digests.config_execution` only. When a `limit_exhausted` stop tracks consumption, the candidate limit must be **strictly greater** than `consumed`. Failed runs cannot be resumed.

Related: [split-digest decision](../decisions/split-config-digests.md), [operations](../workflows/operations.md).
