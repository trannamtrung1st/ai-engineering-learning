# Install and setup

**Audience:** operators preparing a machine and workspace for a TDP run.

This page is the canonical source for prerequisites, installation, provider setup, and a minimal working config. The [first-run walkthrough](../workflows/first-run.md) links here instead of repeating these facts.

## Prerequisites

- **Python 3.11+** (`requires-python` on the `top-down-planning` package).
- **Working directory:** launch `tdp` from the directory you want used as the process cwd. Config file location does **not** change path resolution. Relative `project.workspace` and `runtime.runs_dir` resolve against that cwd. See [configuration](configuration.md#path-resolution).
- **Cursor CLI on PATH** for production runs (`provider.name: cursor`, the package default). The adapter looks for `agent` or `cursor-agent` unless `provider.binary` is set. `tdp run` is non-interactive: the Cursor adapter passes `--force` so agent turns can run shell / `tdp agent` tools.
- **POSIX environment** for cross-process resume locking (`fcntl` flock). Windows Python is not supported for multi-process resume locking. `CursorProvider` also fails fast on Windows (`ProviderUnsupportedPlatformError`).

Optional:

- Desktop notifications: Python extra `[notifications]` (`notify-py`). Without it, notifications are silently skipped. See [observability](observability.md).
- Tests and packaging tools: extra `[dev]` (pytest). Not required to run `tdp`.

The `stub` provider is for scripted tests only (`script_turn()`). Do not use it as an interactive `tdp run` provider.

## Installation

From a clone of this repository, install shared infra then TDP (package README quickstart):

```bash
cd tools/top_down_planning
python -m pip install -e ../core_tools
python -m pip install -e ".[dev]"
cd ../..
```

Runtime-only install can omit `[dev]`. Add desktop alerts with `python -m pip install -e ".[notifications]"` after `core_tools` is installed.

Confirm the CLI:

```bash
tdp --help
tdp agent help
```

## Provider setup

```yaml
provider:
  name: cursor          # cursor | stub
  # binary: /path/to/agent   # optional; otherwise agent or cursor-agent on PATH
  # skip_probe: false        # skip CLI version probe when true
```

- `cursor` — production adapter. Requires the Cursor CLI on PATH.
- `stub` — **tests only**. Not a production provider.

Per-role and per-activity model selection uses `agent_context.roles.<role>.model` and `agent_context.activities.<activity>.model`, each falling back through `agent_context.default.model`. `model: auto` means no explicit Cursor `--model` argument.

## Minimal working config

Canonical example: [examples/top-down-planning.yaml](../../examples/top-down-planning.yaml). That file sets `runtime.runs_dir`, so `tdp run` does not need `--runs-dir`. `tdp run` / `tdp prepare` / `tdp execute` do **not** fall back to `./runs`.

```yaml
version: 1

runtime:
  runs_dir: .tdp/runs

project:
  workspace: .

run:
  input_refs:
    - tools/top_down_planning/README.md
  output_goal: "Produce the requested project output while preserving the declared scope and satisfying the approved plan."

provider:
  name: cursor

agent_context:
  default:
    model: auto
```

Use either `run.output_goal` or `run.output_goal_file` (UTF-8 file resolved against `project.workspace`), not both. From the repository root:

```bash
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml
```

That command defaults to `--until plan`. After this page, complete one successful run with the [first-run walkthrough](../workflows/first-run.md), which explains later `--until` milestones. Inspect and resume catalogs: [user CLI](cli.md) and [operations](../workflows/operations.md).

Related: [configuration](configuration.md), [package README](../../README.md).
