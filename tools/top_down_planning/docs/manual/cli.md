# User CLI

**Audience:** operators invoking TDP from the shell.

Command names, flags, and defaults below come from `tdp --help` and the per-command `--help` text. Agent subcommands: [agent CLI](../agents/cli.md). Staged-run procedures: [operations](../workflows/operations.md). Prepared execution procedures: [prepared execution and Sub-TDPs](../workflows/prepared-and-sub-tdp.md).

Shared presentation flags (`--stream-json`, `--log-level`, `--color`, `--no-notify`, and related) are documented on [observability](observability.md). Omitted presentation flags do not override YAML/`--set`.

`--set PATH=VALUE` is on `tdp run` and `tdp resume` (and `prepare` / `execute` for allowed overrides). Do not add a dedicated flag per semantic config leaf.

## Run-store location

| Command | `--runs-dir` fallback |
| --- | --- |
| `run`, `prepare`, `execute` | `--runs-dir` > `$TDP_RUNS_DIR` > `runtime.runs_dir` in `--config`. **No** `./runs` fallback. |
| `resume`, `status`, `inspect`, `validate`, `doctor`, `sub-tdp attach` | `--runs-dir` > `$TDP_RUNS_DIR` > `runtime.runs_dir` in `--config` > `./runs` |

## `tdp run`

Start a new planning run. `--until` **defaults to `plan`** (planning construction). Omitting `--until` is not a full run.

```bash
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml --until validated
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml --until completed
tdp run --config cfg.yaml --set planning.max_depth=5
```

| Option | Meaning |
| --- | --- |
| `--config` | YAML configuration file. Location does not affect path resolution. |
| `--set PATH=VALUE` | Repeatable resolved-config override. Unknown paths are rejected. |
| `--until {plan,validated,completed}` | Continue until planning construction (`plan`, **default**), plan validation (`validated`), or final outcome (`completed`). |
| `--force` | Allow starting a new run when paused runs still have orphan agent processes in the workspace. |

`--until` and `--force` change how far the engine goes or whether a new run may start. They are not presentation flags. Resume omit-`--until` (one orchestrator step) is a different default: see `tdp resume` below.

## `tdp prepare`

Plan, review, approve, and materialize an **immutable** execution package.

```bash
tdp prepare --config <project.yaml> --output .tdp/execution
tdp prepare --planning-run <run-id> --output .tdp/execution --runs-dir <runs-root>
```

| Option | Meaning |
| --- | --- |
| `--output` | Output directory for the package |
| `--replace` | **Replaces** an existing package at `--output` |
| `--planning-run` | Materialize from an existing validated planning run id (`--config` optional with `--runs-dir`) |

## `tdp execute`

Execute a prepared parent graph or a single unit from `manifest.json`. Semantic config loads from the package.

```bash
tdp execute --manifest .tdp/execution/manifest.json --runs-dir <runs-root>
tdp execute --manifest .tdp/execution/manifest.json --parent-only --runs-dir <runs-root>
tdp execute --manifest .tdp/execution/manifest.json --unit <unit-id> --runs-dir <runs-root>
```

| Option | Meaning |
| --- | --- |
| `--manifest` | **Required.** Path to `manifest.json` (that filename). |
| `--unit` | Execute one prepared unit instead of the parent graph |
| `--parent-only` | Create the parent, enter `sub_tdps`, pause for attach (`stop.code=sub_tdps_awaiting_children`) |
| `--upstream UNIT=RUN_ID` | Repeatable explicit upstream accepted child for a dependency unit |
| `--baseline RUN_ID` | Repeatable accepted child whose workspace changes join the cumulative baseline for `--unit` (not a semantic dependency) |

`--parent-only` and `--unit` change orchestration. Optional `--config` / presentation `--set` on execute are limited to observability, notifications, and run-store location.

## `tdp resume`

Resume an interrupted run. **State-changing** unless `--check`. Failed runs cannot be resumed.

```bash
tdp resume --run <run-id> --config cfg.yaml
tdp resume --run <run-id> --check --config cfg.yaml
tdp resume --run <run-id> --until completed --config cfg.yaml
tdp resume --run <run-id> --allow-config-drift --config cfg.yaml
```

| Option | Meaning |
| --- | --- |
| `--run` | Run id |
| `--check` | Print the resume plan and semantic lifecycle diagnostics; no writes or provider calls. See [troubleshooting](troubleshooting.md). |
| `--allow-config-drift` | Accept contract and model config changes on resume (see [configuration](configuration.md#resume-and-drift)) |
| `--until {plan,validated,completed}` | Loop after apply. Omit to advance **one** orchestrator step (default). |

## `tdp status`

Show run status (`--run`, `--config`, `--runs-dir`, `--stream-json`).

```bash
tdp status --run <run-id> --config cfg.yaml
tdp status --run <run-id> --stream-json
```

## `tdp inspect`

Inspect run artifacts. `--view {active,audit}` (default `active`). `audit` includes inactive history.

```bash
tdp inspect --run <run-id> --view active --config cfg.yaml
```

## `tdp validate`

Run deterministic validators for the run. Does not send desktop notifications.

```bash
tdp validate --run <run-id> --config cfg.yaml
```

## `tdp doctor`

Report run/workspace hygiene issues and orphan agent processes.

```bash
tdp doctor --run <run-id> --config cfg.yaml
tdp doctor --config cfg.yaml
tdp doctor --fix --config cfg.yaml
```

`--fix` is **state-changing**: reconcile stale running runs, kill orphan agents, and remove leftover `.creating-*` staging directories. Omit `--run` for workspace-level diagnostics.

## `tdp sub-tdp attach`

Attach an independently completed child run to parent orchestration.

```bash
tdp sub-tdp attach --parent <parent-run-id> --child <child-run-id> --runs-dir <runs-root>
```

`--parent` and `--child` are required. Attach requires the parent `phase=sub_tdps` and `status=paused`. The child must be completed/accepted with whole-output approval. This command mutates parent orchestration state; do not hand-edit `production.json` instead.

Related: [install](install.md), [run store](run-store.md), [troubleshooting](troubleshooting.md).
