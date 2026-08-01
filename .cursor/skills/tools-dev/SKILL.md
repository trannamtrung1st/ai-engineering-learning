---
name: tools-dev
description: >-
  Develop and test packages under tools/ (core_tools, top_down_planning). Generate
  fast unit tests using fakes, stubs, and mocks instead of live I/O, providers, or
  long sleeps. Use when working in tools/, writing pytest files, or when the user
  asks for unit test coverage.
---

# Tools Dev

Conventions for developing packages under `tools/`. When writing tests, keep them fast — live providers, network calls, subprocesses, and long sleeps make the suite slow.

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

### CLI tests

Use in-process `run_cli()` from `tests/conftest.py` — not `subprocess.run(["tdp", ...])`.

```python
from unittest.mock import patch
from tests.conftest import run_cli

with patch("top_down_planning.cli.user.emit_message"):
    result = run_cli(["status", "--run", run_id, ...])
```

### Shared helpers

Read `tests/helpers.py` first. Common utilities:

- `done_events()`, `respond_review()`, `apply_plan()`, `apply_production()`
- `script_reviewer_allocate()`, `mandatory_initial_respond_request()`
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

## Workflow

1. Identify the unit under test and its dependencies (provider, store, filesystem, CLI).
2. Choose the lightest fake: direct args → stub → patch → short sleep (last resort).
3. Check existing tests in the same module for patterns to copy.
4. Place under `tests/unit/` unless the test needs a multi-phase lifecycle (`tests/integration/`, still use `stub`).
5. Run the single test file and confirm it finishes quickly.

## Checklist

- [ ] No live Cursor CLI, agent subprocess, or network in unit tests
- [ ] Provider orchestration uses `StubProvider.script_turn()` (or `fake_runner` for adapter tests)
- [ ] Reused package test helpers where applicable
- [ ] No sleep unless timing/process lifecycle is under test, and ≤100ms
- [ ] Test name describes behavior, not implementation
