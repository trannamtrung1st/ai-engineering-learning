---
name: tools-dev
description: >-
  Develop and test packages under tools/ (core_tools, top_down_planning). Prefer
  YAML + --set path=value for CLI config; avoid redundant dedicated flags. Use TDD
  red-green-refactor: tests from expected outcomes first, then minimal implementation.
  Generate fast unit tests using fakes, stubs, and mocks instead of live I/O,
  providers, or long sleeps. Orchestration lifecycle: canonical persisted state is
  authoritative, transition monotonicity, CommitSpec state+event atomicity, and
  exact limit boundaries. Required for any work under tools/ (see
  .cursor/rules/tools-dev.mdc). Also use when writing pytest files under tools/
  or when the user asks for unit test coverage.
---

# Tools Dev

Conventions for developing packages under `tools/`. Required by `.cursor/rules/tools-dev.mdc` whenever you touch files under `tools/`. For behavior changes, also follow `.cursor/skills/tdd/SKILL.md` (test-first red → green → refactor). When writing tests, keep them fast — live providers, network calls, subprocesses, and long sleeps make the suite slow.

## Fake/stub decision order

After writing the failing test (TDD red), pick the lightest fake for dependencies:

1. **Direct call** — test with plain inputs; no provider or filesystem needed.
2. **Stub/fake** — `StubProvider`, in-memory stores, `tmp_path`, injected `fake_runner`.
3. **Mock/patch** — `unittest.mock.patch` at I/O boundaries (CLI emit, atomic writes, `create_provider`, event append, `Path.replace` mid-commit).
4. **Short sleep** — only when timing/process lifecycle is the behavior under test; keep ≤100ms.
5. **Live implementation** — rare; integration tests only, and still prefer `stub` provider. Cross-process ownership acquisition is the other exception (two real processes).

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
- `mark_session_stalled(session_id)` to simulate `ProviderTurnStalledError` recovery (not-found: `mark_session_not_found`).
- `mutate_store=callable` to update persistence mid-turn without sleeping.
- Producer batch and completion-claim boundaries, owner `review record-actions` boundaries, and reviewer `review respond` boundaries abort the in-flight turn, wait for `wait_turn_settled`, then close the turn (producer queues the next turn on the same session; whole-output owner revision closes on a new completion claim only; owner advisory closes on record-actions; reviewer releases the bounded session). Pair `CursorProvider.abort_turn()` with `wait_turn_settled()` when callers must block until the collector finishes; `terminate_session()` does both. For collector-thread races, test with `CursorProvider(..., runner=fake_runner)` — not only `StubProvider`.

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

`--set` is on `tdp run` and `tdp resume` only. Dedicated flags are for command routing (`--run`, `--until`, `--check`, `--allow-config-drift`), store bootstrap (`--runs-dir`), output mode (`--stream-json`), presentation toggles wired through `invocation.py` (`--log-level`, `--no-color`, `--no-notify`, `--agent-text`, …; see `cli/main.py` `_add_operational_flags`), or agent per-request args (`tdp agent … --depth`). Omitted presentation flags must not override YAML/`--set`.

New config paths: `config/defaults.py` (`ALLOWED_OVERRIDE_PATHS`), `schema_docs.py`. Presentation paths under `observability.*` auto-join `RESUME_PRESENTATION_ALLOWLIST`; add `notifications.*` (and any other new presentation section) in `config/resume_policy.py`.

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
- `events_append_boundary()`, `recovery_journal_events()` — persistence fault-injection / journal recovery
- `set_capability_token_file()` for CLI tests that exercise mutating `tdp agent` commands
- `mandatory_initial_respond_request()`
- `ensure_input_ref_files()` for config input refs on `tmp_path`

Extend helpers when the same stub setup repeats across tests.

### Orchestration lifecycle

When fixing or extending code under `orchestrator/`, **canonical persisted run state** is authoritative. Returned `RunContinuationResult`, phase results, and CLI outcomes must match it. Outer layers must not overwrite a lower layer's durable lifecycle decision. Finding IDs and audit history live in the orchestration review ledger (Slice 4 freeze evidence).

#### Canonical state authority

Once a layer durably moves a run out of `running` (`paused`, `failed`, `completed`), outer error handling must **preserve** that decision:

1. Reload canonical run before applying a generic failure/pause transition.
2. If status already changed from entry state, report the secondary error separately — do not apply another lifecycle transition.
3. `SessionRecoveryPaused` means the pause is **already persisted** (e.g. `provider_unavailable`). Return current run state or propagate distinctly; never map it to `ProviderRunError` and re-pause as `provider_turn_failed`.

Test matrix: provider replacement failure in whole-plan reviewer, whole-output reviewer, owner revision, focused review, amendment planner — exactly one pause, final `stop.code` unchanged, revision count reflects only the intended mutation.

#### Transition monotonicity

Enforce allowed source→destination matrices centrally in `run_transitions.py` (`pause_run`, `fail_run`, `complete_run_with_outcome`) and in `failure.py` (`mark_run_failed`). Engine generic handlers must reload before calling `mark_run_failed` so an operational `paused` run is not escalated to `orchestrator_invariant_failure`. Do not rely on callers to guard source state.

```text
running → paused | failed | completed
paused  → running (validated resume only) | failed (explicit escalation)
completed / failed → no lifecycle mutation
```

Regression assertions for refused transitions:

- no status/stop/outcome mutation;
- run revision unchanged;
- no extra lifecycle event.

#### Stop codes and resume

Every emitted `stop.code` must exist in the lifecycle model (`domain/run_lifecycle.py`: `PausedStopCode`, `PAUSED_STOP_CODES`; `orchestrator/resume_stop_validators.py`: `validate_stop_for_resume_apply`; resume validators; CLI/status docs) **before** orchestration emits it. Register new operational stops (e.g. `prepared_plan_amendment_required`) through the full schema path — not ad-hoc strings in engine/production.

`apply_resume_plan_atomically()` in `orchestrator/apply_resume.py` revalidates at apply time — never trust prepare-time checks across the prepare/apply boundary:

- actual `status` equals `state_transition.from_status`;
- prior stop matches `state_transition.prior_stop_code` when relevant;
- terminal runs (`failed`, `completed`) cannot become `running`.

Craft invalid `ResumePlan` instances directly in tests.

#### State + event atomicity

Every lifecycle transition and its required audit event share one `CommitSpec` commit. Do not add new split `save_run` + `append_event` lifecycle sequences — migrate existing split paths to `CommitSpec`.

Fault-injection helpers (persistence layer):

- `events_append_boundary(events_path)` — journal byte state before txn append;
- `recovery_journal_events(txn_id, events)` — normalized recovery metadata;
- `top_down_planning/tests/unit/test_commit_crash_recovery.py` — `patch(Path.replace, …)` mid-commit patterns.

Orchestration fault injection — `patch` at I/O boundaries:

- post-pause semantic event append fails → original stop survives, status stays `paused`, no `orchestrator_invariant_failure` overwrite;
- crash after phase save but before required event → fault test proves migration to `CommitSpec` or deterministic restart handling;
- capability revocation fails before run CAS → retry reconstructs capability state.

#### Limits — exact boundary semantics

Configured limits are **maximum allowed attempts** (exact N, not N+1):

| Config path | Meaning | Test |
| --- | --- | --- |
| `limits.whole_plan_review.max_revision_cycles` / `limits.whole_output_review.max_revision_cycles` | exactly N owner revision attempts (mandatory review) | limit 1 → one revision; limit 2 → two; third → limit pause |
| `limits.focused_plan_review.max_revision_cycles_per_loop` / `limits.focused_output_review.max_revision_cycles_per_loop` | same semantics for focused review | same boundary tests |
| `limits.production.max_agent_turns_per_batch` | N unfinished turns, never start turn N+1 | limit 1 → one turn, no second started |
| `limits.amendment.max_revision_cycles_per_request` | exactly N planner turns per amendment request | limit 1 → one turn; pause before turn N+1 (`revision_cycles >= max` after each turn) |
| `limits.planning.max_items_added` | hard cap on plan item count | candidate-ready at cap allowed; one over cap is `limit_exhausted` even on candidate-ready signal |

Enforcement patterns (do not mix):

- **Review driver** (`review_loop_driver.py`): increment revision counter on `changes_requested` / `needs_revision`, then block with `revision_cycles > max_cycles` before the next owner revision.
- **Production batch** (`production.py`): block before starting a turn when `batch_agent_turns >= max_agent_turns_per_batch`.
- **Amendment planner** (`plan_amendment.py`): increment after each planner turn, block with `revision_cycles >= max_revision_cycles_per_request` before the next turn.
- **Planning items** (`planning.py`): block continuation when `items_added > max_items_added`; on `candidate_plan_ready`, terminate for limit instead of completing when over cap.
- **Budget exhausted checks** (`verification_revision_budget_exhausted`, `scope_review_budget_exhausted` in `domain/reviews.py`): use `>=` to mean “limit already consumed” on resume/retry — not the pre-increment gate above.

Assert the **provider turn is not started** when over budget (completion-claim and session-recovery replacement paths too).

#### Terminal and continuation result semantics

`RunContinuationResult.ok` derives from durable outcome, not `status == completed` alone:

```text
completed + accepted → ok=True
completed + blocked/rejected → ok=False
failed / paused → ok=False
```

Repeated `continue_run()` on terminal runs returns the **same** semantic success/failure.

For `until`: evaluate lifecycle stop (`paused`, `failed`, `completed`) **before** `_target_reached()` on each `continue_run` iteration. Do not return `ok=True` on a paused/failed run because a historical phase predicate matches. `ok` on a **running** run that satisfies `until` remains `True` (target met while still running). `RunContinuationResult.target_reached` mirrors `_target_reached(run, until)` at return time and is independent of `ok`.

`RunContinuationResult.cancelled` must be `True` when durable stop is `user_cancelled`, including Sub-TDP child Ctrl-C propagation and early `continue_run` returns on an already-paused run. Durable `user_cancelled` with `cancelled=False` is a defect. `finalize_user_cancel` persists `user_cancelled` before orphan cleanup; cleanup failures must not skip cancellation.

Use `continuation_ok_from_run()` from `domain/run_lifecycle.py` for engine, `apply_resume`, and CLI resume — `completed + accepted` only is success.

Review limit/termination paths call `ReviewLoopDriver.result_from_run(run, ..., loop=loop)` (via orchestrator `_driver_host()` or direct driver use) so returned `loop_id`, `reviewer_session_id`, and `revision_cycles` match persisted state.

**Sub-TDP child failure**: permanent child failure must `fail` the parent immediately with `sub_tdp_unit_permanently_failed` — do not pause with resumable `sub_tdp_child_failed`. Implement a resumable `sub_tdp_child_failed` pause only when `prepare resume → apply resume → continue` executes a defined repair action (retry, replace, or reset the unit); resume alone must not convert the pause into permanent failure.

**Amendment activation** (`plan_amendment.py`): only idempotent `running`/no-stop, or `paused` with exact `amendment_pending` whose amendment ID matches production state. Reject failed/completed/unrelated pauses via the same transition validator as resume.

#### Engine boundary and preflight

Before `create_provider`:

- validate phase/state matrix (focused review: `running` + correct phase; unsupported phase → no provider side effects);
- wrap phase entry (config load, workspace, provider factory, phase execution) in one orchestration boundary with classified failure;
- continuation preflight (session policy, orphan cleanup, capability revocation) is lifecycle work — partial mutation plus a raw exception is a defect.

Cancellation durability: durable `paused` / `user_cancelled` must persist even when `teardown_provider_sessions()`, audit append, or orphan scan raise. `finalize_user_cancel` runs after teardown in `finally`; teardown errors are swallowed when `cancelled` is set. Happy-path and teardown-fault Ctrl-C are covered in `test_operational_failures.py`.

#### Ownership and orphans

Cross-process ownership acquisition uses an advisory flock on a **persistent** `.resume.lock.d/.owner.lock` sentinel inode (never unlinked during release or cleanup); the flock is the authoritative live-owner primitive — free flock means no live owner, and stale `owner.json` cannot block acquisition. Final acquisition is nonblocking (`LOCK_NB`). Ephemeral `owner.json` is cleared only while the flock is held, before unlock (best-effort on release); only the matching owner token can release the bound flock FD. In-process ownership is a single `_OWNERSHIP_REGISTRY` record `{owner_token, fd}` with atomic publish/rollback on acquire failure; rollback is **token-scoped** (never pop/release a foreign winner) and first acquisition is serialized under `_ACQUIRE_LOCK` (precheck → flock → publish). Disk stale-lock cleanup must **not** mutate `_OWNERSHIP_REGISTRY` for other runs or active owners. Rollback/release flock unlock+close runs under deferred SIGINT/SIGTERM with registry pop in a `finally` so interrupt cannot strand flock without clearing registry; metadata cleanup `OSError` records `ownership_cleanup_failed` diagnostics via `ownership_cleanup_failures()` without masking release.

Orphan detection includes **completed** and **failed** runs — any tagged live provider on a terminal run is an orphan. Keep autouse `stub_orphan_agent_scan` in orchestration tests; exercise scan logic in `top_down_planning/tests/unit/test_agent_process_cleanup.py` with injected PIDs.

#### Mandatory review crash idempotency

Review approval, run phase transition, and required approval event share one `CommitSpec` commit — not separate loop save + phase save + event append. Crash after loop approval without phase advance must not spawn a second mandatory loop or duplicate reviewer session.

#### Orchestration change requirements

Every orchestration lifecycle change ships:

1. implementation;
2. targeted regression test (expected outcome from spec, not current code);
3. fault/crash injection test when persistence ordering matters;
4. proof canonical run state matches returned API/CLI result;
5. proof repeated invocation is idempotent where applicable;
6. proof required lifecycle event exists exactly once or is explicitly idempotent;
7. no new orphan provider/session/capability state;
8. no weakening of revision CAS or lineage validation.

## `core_tools` conventions

- **Provider adapter**: test `CursorProvider` with an injected `fake_runner` and `skip_probe=True` — never a live agent binary.
- **Idle stream timeout**: use short `limits.provider.turn_idle_timeout_seconds` (≤0.1s) with a blocking `fake_runner`; orchestration stall recovery uses `StubProvider.mark_session_stalled()`.
- **Orchestration-free logic**: call functions directly; no provider needed.
- **Process lifecycle** (`core_tools/tests/unit/test_process_cleanup.py`): subprocess + `time.sleep(0.1)` is acceptable when termination is the behavior under test.

```python
from core_tools.provider import CursorProvider

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
# BAD — implement orchestration first, then assert whatever the store ended up with
engine.continue_run(run_id)
assert store.get_run(run_id)["status"] == "planning"  # copied from a debug run

# GOOD — spec says resume after mandatory review clears → status "planning"
def test_resume_after_mandatory_review_clears_sets_planning(tmp_path):
    ...
    assert store.get_run(run_id)["status"] == "planning"
# run → red → implement continue_run path → green
```

```python
# BAD — live Cursor via default create_provider (config provider.name=cursor)
from core_tools.provider import create_provider
RunEngine(store, create_provider=create_provider).continue_run(run_id)

# GOOD — inject StubProvider (direct engine test or CLI patch)
provider = StubProvider()
provider.script_turn(done_events(signal="candidate_plan_ready"))
RunEngine(store, create_provider=lambda _cfg, _ws: provider).continue_run(run_id)
# CLI tests: patch("top_down_planning.cli.user.create_provider", return_value=provider)
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

# GOOD — autouse suppress_desktop_notifications in tests/conftest.py;
# per-test bridge_send_mock / outcome_send_mock when asserting sends
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

```python
# BAD — SessionRecoveryPaused becomes ProviderRunError → engine re-pauses as provider_turn_failed
except SessionRecoveryPaused:
    raise ProviderRunError(...)

# GOOD — recovery pause already persisted (planning/production pattern)
except SessionRecoveryPaused as exc:
    return self._result_from_run(
        self._store.load_run(self._run_id),
        ok=False,
        reason=str(exc),
    )
```

```python
# BAD — assert only status after orchestration (misses stop overwrite / revision drift)
engine.continue_run(run_id)
assert store.get_run(run_id)["status"] == "paused"

# GOOD — assert full durable contract from spec
run = store.get_run(run_id)
assert run["status"] == "paused"
assert run["stop"]["code"] == "limit_exhausted"
assert run["revision"] == revision_before + 1
result = engine.continue_run(run_id)  # repeat call
assert result.ok is False  # same semantic outcome as first terminal call
```

```python
# BAD — limit test allows N+1 attempts
assert revision_cycles >= max_cycles  # checks after increment → off-by-one

# GOOD — limits.whole_plan_review.max_revision_cycles=1 allows exactly one owner revision
# script: changes_requested → owner revision → changes_requested again → limit pause
```

```python
# BAD — emit stop code not registered in PausedStopCode / resume validators
from top_down_planning.domain.run_lifecycle import StopRecord
pause_run(store, run_id, stop=StopRecord(code="prepared_plan_amendment_required", ...))

# GOOD — register in domain/run_lifecycle.py + resume_stop_validators.py first, then emit
```

```python
# BAD — split state save and required event (do not add new lifecycle paths like this)
store.save_run(...)
store.append_event(...)

# GOOD — one commit (pause_run / run_transitions already use this pattern)
from top_down_planning.persistence.commit import CommitSpec
store.commit(
    run_id,
    CommitSpec(
        run=updated,
        run_expected_revision=expected_revision,
        events=[{"type": "run_paused", "run_id": run_id, ...}],
    ),
)
```

## Workflow (TDD + fakes)

Follow `.cursor/skills/tdd/SKILL.md` — red → green → refactor. Under `tools/`, combine with the fake/stub decision order above.

1. **Red** — from spec/requirements, write a failing test with expected observable outcome (return value, store state, CLI exit/message).
2. Identify dependencies (provider, store, filesystem, CLI) and choose the lightest fake: direct args → stub → patch → short sleep (last resort).
3. Run the test; confirm it fails for the right reason (missing/wrong behavior).
4. **Green** — minimal production change; re-run until pass.
5. Check existing tests in the same module for patterns to copy.
6. Place under `tests/unit/` unless the test needs a multi-phase lifecycle (`tests/integration/`, still use `stub`).
7. **Refactor** if needed; confirm the file still finishes quickly.

Do not implement orchestration/CLI logic first and then write assertions that mirror the accident.

## Checklist

- [ ] Failing test written from expected outcomes before production code (TDD)
- [ ] Semantic config via YAML + `--set` only; no mirrored `--param` flags
- [ ] New paths in `config/defaults.py` (`ALLOWED_OVERRIDE_PATHS`), `schema_docs.py`
- [ ] Presentation fields wired through `invocation.py` (package root, not under `cli/`) if dedicated flags added
- [ ] No live Cursor CLI, agent subprocess, network, desktop notifications, or full-system PID scans in unit tests
- [ ] Provider orchestration uses `StubProvider.script_turn()` (or `fake_runner` for adapter tests)
- [ ] Reused package test helpers where applicable
- [ ] No sleep unless timing/process lifecycle is under test, and ≤100ms
- [ ] Test name describes behavior, not implementation
- [ ] Lifecycle: central transition guards; terminal states not rewritten; refused transitions leave revision/events unchanged
- [ ] Lifecycle: lower-level persisted stop preserved — reload before outer generic failure; `SessionRecoveryPaused` not re-paused; `mark_run_failed` does not escalate operational `paused`
- [ ] New `stop.code` registered in lifecycle/resume schema before orchestration emits it
- [ ] Lifecycle transition + required audit event in one `CommitSpec`; no new split lifecycle writes
- [ ] Limit tests use exact-N semantics and correct `limits.*` paths; `ok`/`cancelled` match durable outcome
- [ ] Orchestration tests assert canonical run matches returned result; repeated terminal `continue_run` idempotent
- [ ] `until`: lifecycle stop evaluated before target predicate on reload; `target_reached` not conflated with `ok`
- [ ] Cross-process ownership tests use real subprocesses; orphan scan tests cover terminal runs
