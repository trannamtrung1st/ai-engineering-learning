# Configuration resolution, digests, and snapshots

**Audience:** maintainers of config merge, resume, and snapshot policy.

Operator-facing tables: [configuration](../manual/configuration.md). Split-digest rationale: [split-digest decision](../decisions/split-config-digests.md).

## Resolution

Product defaults live in `DEFAULT_CONFIG`. YAML `--config` deep-merges, then repeatable `--set path=value`. Unknown keys are rejected (`ALLOWED_OVERRIDE_PATHS`). Semantic vs presentation override surfaces: [configuration](../manual/configuration.md#precedence).

Path roots: `project.workspace` and `runtime.runs_dir` against process cwd; input refs, output-goal file, and agent_context file entries against resolved workspace. Absolute paths used directly. Resource paths must resolve **inside** the workspace; absolute paths, unresolved `..`, and symlink escapes are rejected at collection.

Published schema: `tdp agent schema config`.

## Digest axes

Approvals and resume bind **split** digests (schema v3). The monolithic `digests.config` field is not accepted.

| Digest | Projection | Typical use |
| --- | --- | --- |
| `config_contract` | Semantic config minus `limits`, `observability`, `notifications`, and `runtime.runs_dir` | Plan **and** whole-output approval identity (with the other keys below). Whole-output approval additionally binds `output` and `context_snapshot`; plan approval does not. |
| `config_execution` | `limits` only (including `limits.provider.max_retries_per_call`, `turn_idle_timeout_seconds`, and `max_stream_json_record_bytes`) | Limit changes on resume without invalidating approvals |
| `context_spec` | Declarations: models, guidance entries, resource/skill selection (including packaged `tdp:builtin:` keys), snapshot exclusion policy | Resume of non-model context; session identity |
| `context_snapshot` | Materialized resource bytes, skill contents, guidance text/file digests | Drift detection during production. Bound on **whole-output** approval when present; not a plan-approval key. |
| `input` / `output_goal` | Run contracts | Creation and resume of goal/input files |
| `plan` / `output` | Canonical plan / production output | Review target digests. `output` is an approval key only on whole-output approval, not on plan approval. |

`observability.*`, `notifications.*`, and `runtime.runs_dir` are presentation: they do not enter contract or execution digests.

## Workspace snapshots

The context snapshot is a compact binding (workspace-relative POSIX paths, bare lowercase hex digests, no `sha256:` prefix):

- `resource_digests` — map of path → digest
- `skill_digests` — map of path → digest
- `guidance_digests` — list of `{path, text, digest}` objects

Persisted on the run as `context_snapshot_binding`. List-shaped `{path, digest}` resource entries, absolute keys, and a binding-level `workspace` field are rejected (recreate the run). Direct file resources always bind (missing files use a sentinel digest) even if they match an exclude pattern. Directory/glob expansion is filtered by excludes.

`context_snapshot.excludes` (default-on): built-ins cover `__pycache__`, `*.py[cod]`, common tool caches; `patterns` are gitignore/gitwildmatch via pathspec. TDP does **not** inherit `.gitignore`. Empty `patterns` does not disable built-ins (`defaults: false` does). Exclusion policy participates in `context_spec`. Exclusions apply to **resource** materialization only, not skills or guidance.

Agent session resource **manifests** may still list cache files from recursive expansion; snapshot excludes are for integrity binding, not manifest hygiene.

## Drift rules

Resume validates non-model `context_spec` strictly. Model-only `context_spec` drift is allowed before whole-plan approval with `--allow-config-drift`. `context_snapshot` is skipped only during `production` so in-flight authorized mutations can proceed.

Each `production apply` validates cumulative snapshot drift against the candidate batch. **Resource** path drift can be authorized by declaring the path in `outputs`. **Skill and guidance** keys cannot (`production_context_mutation_unauthorized`). Incomplete resource evidence: `production_evidence_incomplete`. Snapshot validation runs **before** artifact capture and before `production.json` updates. Completion re-validates hash-matched evidence (latest capture per path must match workspace bytes), then rebases `context_snapshot` when authorized (`context_snapshot_rebased`).

Whole-output and focused-output owner revisions that change resources rebase `context_snapshot` and `digests.output` atomically when the owner turn closes.

Evidence `ref` values use the same canonical relative path model as binding keys (`canonicalize_evidence_ref`).

Related: [persistence](persistence.md), [security](security.md), [sessions](../architecture/sessions.md).
