# Prepared execution and Sub-TDPs

**Audience:** operators using prepared packages and parent/child TDP runs.

Plan once, materialize an immutable execution package, then run a parent graph or individual units without re-planning. Package integrity internals: [prepared packages](../internals/packages-and-sub-tdp.md). Flags: [user CLI](../manual/cli.md). Do not hand-edit parent `production.json` → `sub_tdps`.

## Prepare

```bash
tdp prepare --config <project.yaml> --output .tdp/execution
tdp prepare --planning-run <run-id> --output .tdp/execution --runs-dir <runs-root>
```

`--output` is the package directory. `--replace` **replaces** an existing package there. The entry point is `manifest.json` (that filename). Persisted package IDs are immutable: the store rejects a second package with the same `package_id` and a different digest.

`--planning-run` materializes from an existing **validated** planning run. `tdp execute` loads semantic config from the package; it does not require `cwd/config.yaml`.

## Execute the parent graph

```bash
tdp execute --manifest .tdp/execution/manifest.json --runs-dir <runs-root>
```

`--runs-dir` (or `$TDP_RUNS_DIR` / `runtime.runs_dir`) is required; `execute` does not fall back to `./runs`.

Parent path after children are accepted: `sub_tdps` → synthesize child results → parent production (integration) → completion → `whole_output_review` → acceptance.

## Parent-only, then attach

```bash
tdp execute --manifest .tdp/execution/manifest.json --parent-only --runs-dir <runs-root>
```

Creates the parent, enters `sub_tdps`, and **pauses** (`stop.code=sub_tdps_awaiting_children`) so independently executed units can attach.

```bash
tdp sub-tdp attach --parent <parent-run-id> --child <child-run-id> --runs-dir <runs-root>
tdp resume --run <parent-run-id> --runs-dir <runs-root>
```

Attach requires parent `phase=sub_tdps` **and** `status=paused`. The child must be `completed` / `accepted` with whole-output approval on the child run. Dependencies must already be attached with matching `accepted_result_digest` values before a dependent unit can attach. The child's embedded `unit_id` is authoritative.

After every unit is attached, `tdp resume` on the parent continues synthesis, integration production, and whole-output review.

A permanently failed Sub-TDP unit fails the parent (`sub_tdp_unit_permanently_failed`) rather than leaving it `running`. Failed runs cannot be resumed.

## Direct unit execution

```bash
tdp execute --manifest .tdp/execution/manifest.json --unit <unit-id> --runs-dir <runs-root>
```

Prepared children load the assigned subtree and inherited context; they do **not** enter planning.

### Dependencies (`--upstream`)

Direct `--unit` execution with `depends_on` requires an explicit complete `--upstream dep=<child-run-id>` map (repeatable `UNIT=RUN_ID`). Each upstream run must belong to the mapped dependency unit and pass accepted-delivery validation.

### Baseline (`--baseline`)

`--baseline <accepted-run-id>` (repeatable) includes workspace changes from unrelated accepted siblings in the cumulative workspace baseline. It does **not** create a semantic dependency. Use `--upstream` for `depends_on` bindings.

Child creation authorizes configured **resource** snapshot drift from that baseline using content-bound accepted-result workspace changes. Guidance and skill drift are always rejected. Integrity rules: [prepared-execution integrity](../decisions/prepared-execution-integrity.md).

Related: [lifecycle](lifecycle.md), [operations](operations.md), [troubleshooting](../manual/troubleshooting.md).
