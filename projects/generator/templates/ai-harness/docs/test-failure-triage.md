# Test Failure Triage — Integration, E2E, and Flakes

Runbook for harness agents and operators when `aih:check`, `test:integration`, `test:e2e`, or `test:playwright-ui` fail intermittently or across slices.

**Related:** [11-testing-plan.md](../../docs/technical/11-testing-plan.md) §5.4, §13 · [13-docker-compose-local-runtime.md](../../docs/technical/13-docker-compose-local-runtime.md) §12 · [07-state-machines.md](../../docs/technical/07-state-machines.md) §8 · [implementer.prompt.md](../agents/implementer.prompt.md) (Cross-slice test failures)

---

## Decision tree

```
Test failure in aih:check
  │
  ├─ DB / container not healthy?
  │    └─ YES → docker compose ps; aih:dev:db:up or aih:test:stack:reset → re-run
  │
  ├─ Fails only in full suite, passes in isolation?
  │    └─ YES → cross-suite pollution — **fix isolation in owner slice** (not bare re-run of aih:check); see Integration flake patterns + harness triage report
  │
  ├─ Failure path owned by current slice (scope hint or completionArtifacts)?
  │    └─ YES → fix in scope; do not defer
  │
  ├─ Failure path owned by another slice?
  │    └─ YES → isolate once, reset test stack once → still fails → SLICE_DEFER
  │
  └─ No clear owner, infrastructure OK, reproducible in isolation
       └─ SLICE_BLOCKED with evidence
```

**Before `SLICE_DEFER`:**

1. Run the failing suite in isolation: `npm run aih:run-check -- test:integration -w {{WORKSPACE_NAME}}api -- <file-pattern>`
2. Reset test stack once: `npm run aih:test:stack:reset`
3. Re-run isolated suite; if still failing and scope hints name another owner, revert in-scope changes and defer.

**Do not treat a passing full-suite re-run as a fix.** When isolated pass + full-suite fail, apply an isolation fix in the owning slice or defer — never close the iteration with "passes on re-run" alone.

---

## Harness integration triage report

When `computationalChecks.integrationFailurePolicy.investigateOnFailure` is enabled (default in `ralph-loop.json`), Ralph runs mechanical triage after `test:integration` fails:

1. Parse failing test file(s) and `TC-*` case id(s) from `{run-id}-check-test-integration.log`
2. Run the failing file in isolation (single `node --test` file via harness triage)
3. Write `{run-id}-integration-triage.json` and merge into `{run-id}-checks.json` under `triage`

| `triage.classification` | Meaning | Required action |
| --- | --- | --- |
| `crossSuiteFlake` | Full suite failed; isolated file passed | Fix parallel pollution in **owner slice** (afterEach restore, dedicated section/session fixtures) |
| `reproducible` | Fails isolated too | Fix real bug in owner slice tests or product code |
| `infrastructure` | DB/stack errors in log | `npm run aih:test:stack:reset`; not a product skip |
| `unknown` | Could not run isolated probe | Investigate manually from log excerpts |

When `autoReopenOwnerSlice` / `autoFocusOwnerSlice` are enabled, the harness sets `passes: false` on the owner slice and focuses the next iteration via `state/loop-state.json`. The next implementer prompt includes a mandatory **Integration failure investigation** block — read the triage JSON before signaling `SLICE_DONE`.

---

## Infrastructure flake vs product bug

| Symptom | Likely cause | First action |
| --- | --- | --- |
| `db service not healthy` before tests run | Dev or test Postgres container down | `docker compose ps`; `npm run aih:dev:db:up` (preview) or `npm run aih:test:stack:reset` (integration) |
| Empty `review.txt` with exit 0 | Reviewer agent produced no output | Re-run review gate; not a code defect |
| Passes isolated, fails in full `test:integration` | Cross-suite DB pollution, shared seed fixtures, or leaked timers | Fix isolation in **owner slice** — afterEach restore, dedicated section; harness triage classifies as `crossSuiteFlake` |
| Scheduler tick clobbered test fixture | Async job fired after teardown | Stop scheduler before pinning fixtures; no `setTimeout` sleeps |
| HTTP 500 only in full suite | Cross-suite DB pollution or pool contention | Fix owner slice isolation; reset test stack once if infra suspect — do not bare re-run full suite as resolution |
| Playwright timeout on first navigation | Preview stack not up | `npm run aih:preview:verify` before `aih:check` |

---

## Integration flake patterns

### Background scheduler isolation

When production code uses `setInterval` or async ticks (e.g. token rotation, polling), timers survive across specs unless cleared.

**Pattern:** Export a test helper that resets schedulers in `afterEach`:

```typescript
// apps/api/src/modules/<module>/<module>.integration.test.ts
import {
  runIntegrationBeforeSuite,
  runIntegrationBeforeEach,
  type SuiteProfile,
} from "../../infra/integration-test-harness.js";

// before:  await runIntegrationBeforeSuite("module", pool, server);
// beforeEach: await runIntegrationBeforeEach("module", pool);
```

Suite profiles control scoped per-test resets. JWT/session tokens should be cached at suite level — do not re-login in `beforeEach`.

For background schedulers, export a helper that resets timers in `afterEach`:

```typescript
export function installSchedulerTestIsolation(resetFn: () => void): void {
  afterEach(() => { resetFn(); });
}
```

Any integration suite that starts background schedulers must register cleanup.

### Pinned test fixtures

When tests need a fixed fixture that production schedulers would otherwise mutate:

1. Stop the scheduler for the entity under test
2. Remove auto-generated rows
3. Insert pinned fixture with known IDs

Do **not** add `setTimeout` sleeps or retry loops as workarounds. Prefer production `onlyIf` guards so stale ticks abort safely.

### Full-suite-only failures

If a spec passes alone but fails when `npm run test:integration` runs in parallel:

- Check for leaked timers (`afterEach` cleanup)
- Check for shared seed rows mutated without restore (enrollments, sessions on shared fixtures)
- Compare isolated run: `npm run aih:run-check -- test:integration -w {{WORKSPACE_NAME}}api -- <suite-file>`
- **Apply a code fix in the owner slice** — do not rely on a lucky full-suite re-run

### Synchronous background jobs in tests

Deferred jobs (`setImmediate`, `setTimeout(0)`) can race integration assertions. In `NODE_ENV=test`, run deferred work synchronously when the product supports it. Do not add arbitrary waits in tests.

### FK violations in negative tests

Use `NULL` or valid FK references for optional foreign keys in negative-path tests — random UUIDs may violate constraints and surface as HTTP 500.

---

## Commands

| Command | Use |
| --- | --- |
| `npm run aih:test:stack:reset` | Tear down and recreate ephemeral test DB |
| `npm run aih:run-check -- test:integration` | Single check with timeout, heartbeat, log file |
| `npm run aih:run-check -- test:integration -- <pattern>` | Isolated suite or file |
| `npm run aih:check -- <sliceId>` | Pre-browser computational profile (no Playwright UI) |
| `npm run aih:check -- <sliceId> --profile fast` | Scope + typecheck/lint/unit only |
| `npm run aih:playwright-check -- <sliceId>` | Headless Playwright UI regression for slice spec |
| `npm run aih:slice:focus -- <id> --reason "..."` | One-shot next-iteration override |
| `npm run aih:slice:reopen -- <id> --reason "..."` | Set `passes: false` + append history |
| `npm run aih:status` | Pending slices, loop override, recent failures |

**Log paths:** `ai-harness/generated/runs/<run-id>-check-<script>.log`, `*-checks.json`, and `*-integration-triage.json` (when integration triage runs)

Set `AIH_TEST_STACK_RESET=0` to skip volume teardown on reset (faster local debugging; may retain cross-suite state).

With `resetBetweenScripts: false` in `ralph-loop.json` (default), the harness reuses a primed test stack between `test:integration` and `test:e2e` within one `aih:check` run. Force a full reset when investigating cross-suite pollution.

---

## Cross-slice policy

When failures are in tests or modules owned by another slice:

1. Do **not** edit out-of-slice application code or tests.
2. Revert your slice's in-scope uncommitted changes only.
3. Do not touch gate-owned files (`playwright-regression-index.json`, browser-test artifacts).
4. Signal `SLICE_DEFER <owner-slice-id> <reason>` on its own line at the end.

The harness reopens the owner slice, records `history`, and focuses the next loop iteration via `state/loop-state.json`. When integration triage detects `crossSuiteFlake` for an out-of-slice owner, Ralph may reopen and focus that slice automatically without waiting for `SLICE_DEFER`.

---

## Playwright triage

| Issue | Pattern |
| --- | --- |
| Hardware unavailable in CI (camera, GPS, etc.) | `window.__PRODUCT_TEST__` hook exposed by component under test |
| Geolocation / permissions | Stub `navigator.geolocation`, `permissions.query`, `getUserMedia` in `page.addInitScript` |
| Specific API outcomes | `page.route('**/api/...', handler)` |
| Slow network retry UX | Extended `timeout` on `expect` and `test` blocks |

Playwright uses the **preview dev DB**, not the integration test stack. Ensure preview is healthy: `npm run aih:preview:verify`.

See also: [playwright-regression.md](./playwright-regression.md) (Deterministic test hooks).
