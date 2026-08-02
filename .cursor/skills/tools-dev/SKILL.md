---
name: tools-dev
description: >-
  Develop and test packages under tools/ (core_tools, top_down_planning). Prefer
  YAML + --set path=value for CLI config; avoid redundant dedicated flags. Generate
  fast unit tests using fakes, stubs, and mocks instead of live I/O, providers, or
  long sleeps. Required for any work under tools/ (see .cursor/rules/tools-dev.mdc).
  Also use when writing pytest files under tools/ or when the user asks for unit
  test coverage.
---

# Tools Dev

Conventions for developing packages under `tools/`. Required by `.cursor/rules/tools-dev.mdc` whenever you touch files under `tools/`. When writing tests, keep them fast — live providers, network calls, subprocesses, and long sleeps make the suite slow.

## Decision order

1. **Direct call** — test with plain inputs; no provider or filesystem needed.
2. **Stub/fake** — `StubProvider`, in-memory stores, `tmp_path`, injected `fake_runner`.
3. **Mock/patch** — `unittest.mock.patch` at I/O boundaries (CLI emit, atomic writes, `create_provider`).
4. **Short sleep** — only when timing/process lifecycle is the behavior under test; keep ≤100ms.
5. **Live implementation** — rare; integration tests only, and still prefer `stub` provider.

## `top_down_planning` conventions

### Provider orchestration

Use `StubProvider` from `core_tools.provider`. Script each turn before the orchestrator requests it:

```python
from core_tools.provider import StubProvider
from tests.helpers import done_events, minimal_resolved_config, create_run_kwargs

provider = StubProvider()
provider.script_turn(done_events(text="planning turn"))
```

- `script_session_turn(session_id, events)` for reviewer-specific sessions.
- `mutate_store=callable` to update persistence mid-turn without sleeping.

### Config and run setup

```python
from tests.helpers import minimal_resolved_config, create_run_kwargs

config = minimal_resolved_config()  # provider.name defaults to stub
kwargs = create_run_kwargs(tmp_path, resolved_config=config)
store.create_run(run_id, **kwargs)
```

Do not invoke live Cursor in orchestration tests. Metadata strings like `provider="cursor"` are fine.

### CLI design

Prefer **YAML + `--set path=value`**. Do not add dedicated `--param` flags that mirror config leaves.

| Tier | Override surface |
| --- | --- |
| **Semantic** (`planning.*`, `limits.*`, `agent_context.*`, `run.*`, …) | defaults → YAML → `--set` only |
| **Presentation** (`observability.*`, `notifications.*`, `runtime.runs_dir`) | defaults → YAML → `--set` → explicit dedicated flag |

`--set` is on `tdp run` and `tdp resume` only. Dedicated flags are for command routing (`--run`, `--until`), store bootstrap (`--runs-dir`), output mode (`--stream-json`), presentation toggles in `invocation.py` (`--log-level`, `--no-color`, `--no-notify`), or agent per-request args (`tdp agent … --depth`). Omitted presentation flags must not override YAML/`--set`.

New config paths: `ALLOWED_OVERRIDE_PATHS`, `defaults.py`, `schema_docs.py`. Presentation paths under `observability.*` auto-join `RESUME_PRESENTATION_ALLOWLIST`; add `notifications.*` (and any other new presentation section) in `resume_policy.py`.

```bash
tdp run --config cfg.yaml --set planning.max_depth=5
# not: tdp run --max-depth 5
```

### CLI tests

Use in-process `run_cli()` from `tests/conftest.py` — not `subprocess.run(["tdp", ...])`.

```python
from unittest.mock import patch
from tests.conftest import run_cli

with patch("top_down_planning.cli.user.emit_message"):
    result = run_cli(["status", "--run", run_id, ...])

# Config overrides — prefer --set in tests too
result = run_cli(["run", "--config", str(config_path), "--set", "limits.planning.max_agent_turns=3"])
```

### Shared helpers

Read `tests/helpers.py` first. Common utilities:

- `done_events()`, `respond_review()`, `apply_plan()`, `apply_production()`
- `mandatory_initial_respond_request()`
- `ensure_input_ref_files()` for config input refs on `tmp_path`

Extend helpers when the same stub setup repeats across tests.

## `core_tools` conventions

- **Provider adapter**: test `CursorProvider` with an injected `fake_runner` and `skip_probe=True` — never a live agent binary.
- **Orchestration-free logic**: call functions directly; no provider needed.
- **Process lifecycle** (`test_process_cleanup.py`): subprocess + `time.sleep(0.1)` is acceptable when termination is the behavior under test.

```python
def fake_runner(argv: list[str], cwd: Path):
    for line in scripted_lines:
        yield line

provider = CursorProvider(
    config,
    workspace=tmp_path,
    runner=fake_runner,
    binary=str(agent_path),
    skip_probe=True,
)
```

## Anti-patterns

```python
# BAD — live provider in orchestration test
config = minimal_resolved_config(provider={"name": "cursor"})
engine.run(...)  # would spawn real agent

# GOOD — stub provider with scripted turns
provider = StubProvider()
provider.script_turn(done_events(signal="candidate_plan_ready"))
```

```python
# BAD — waiting instead of scripting
time.sleep(2)
assert store.get_run(run_id)["status"] == "completed"

# GOOD — mutate store at the scripted moment
provider.script_turn(
    done_events(signal="candidate_plan_ready"),
    mutate_store=lambda: store.commit(...),
)
```

```python
# BAD — subprocess for unit-level CLI behavior
subprocess.run(["tdp", "run", ...])

# GOOD — in-process (top_down_planning)
from tests.conftest import run_cli
result = run_cli(["run", "--config", str(config_path)])
```

```python
# BAD — real desktop notifications during pytest (macOS notify-py popups)
run_cli(["run", "--config", str(config_path)])  # completes run, fires OS notification

# GOOD — autouse stub in tests/conftest.py; assert sends via bridge_send_mock fixture
def test_progress_notification(bridge_send_mock, tmp_path):
    ...
    assert "Planning candidate ready" in [c.args[0] for c in bridge_send_mock.call_args_list]
```

```python
# BAD — live orphan-agent PID enumeration during orchestration tests (~0.7s per continue_run)
engine.continue_run(run_id, single_step=True)

# GOOD — autouse stub_orphan_agent_scan in tests/conftest.py; test scan logic via direct
# import + injected list_live_pids/read_pid_environ in test_agent_process_cleanup.py
```

## Workflow

1. Identify the unit under test and its dependencies (provider, store, filesystem, CLI).
2. Choose the lightest fake: direct args → stub → patch → short sleep (last resort).
3. Check existing tests in the same module for patterns to copy.
4. Place under `tests/unit/` unless the test needs a multi-phase lifecycle (`tests/integration/`, still use `stub`).
5. Run the single test file and confirm it finishes quickly.

## Checklist

- [ ] Semantic config via YAML + `--set` only; no mirrored `--param` flags
- [ ] New paths in `ALLOWED_OVERRIDE_PATHS`, `defaults.py`, `schema_docs.py`
- [ ] Presentation fields wired through `invocation.py` if dedicated flags added
- [ ] No live Cursor CLI, agent subprocess, network, desktop notifications, or full-system PID scans in unit tests
- [ ] Provider orchestration uses `StubProvider.script_turn()` (or `fake_runner` for adapter tests)
- [ ] Reused package test helpers where applicable
- [ ] No sleep unless timing/process lifecycle is under test, and ≤100ms
- [ ] Test name describes behavior, not implementation
