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
  │    └─ YES → leaked timers / cross-suite pollution → see Integration flake patterns
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

1. Run the failing suite in isolation: `npm run aih:run-check -- test:integration -- <file-pattern>`
2. Reset test stack once: `npm run aih:test:stack:reset`
3. Re-run isolated suite; if still failing and scope hints name another owner, revert in-scope changes and defer.

---

## Infrastructure flake vs product bug

| Symptom | Likely cause | First action |
| --- | --- | --- |
| `db service not healthy` before tests run | Dev or test Postgres container down | `docker compose ps`; `npm run aih:dev:db:up` (preview) or `npm run aih:test:stack:reset` (integration) |
| Empty `review.txt` with exit 0 | Reviewer agent produced no output | Re-run review gate; not a code defect |
| Passes isolated, fails in full `test:integration` | Leaked `setInterval` / background jobs from prior specs | Add per-spec `afterEach` cleanup; `aih:test:stack:reset` |
| Scheduler tick clobbered test fixture | Async job fired after teardown | Stop scheduler before pinning fixtures; no `setTimeout` sleeps |
| HTTP 500 only in full suite | Cross-suite DB pollution or pool contention | Reset test stack; defer to owning slice if persists |
| Playwright timeout on first navigation | Preview stack not up | `npm run aih:preview:verify` before `aih:check` |

---

## Integration flake patterns

### Background scheduler isolation

When production code uses `setInterval` or async ticks (e.g. token rotation, polling), timers survive across specs unless cleared.

**Pattern:** Export a test helper that resets schedulers in `afterEach`:

```typescript
// apps/api/src/infra/integration-test-harness.ts
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

If a spec passes alone but fails when `npm run test:integration` runs sequentially:

- Check for leaked timers (`afterEach` cleanup)
- Reset test stack: `npm run aih:test:stack:reset`
- Compare isolated run: `npm run aih:run-check -- test:integration -- <suite-file>`

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
| `npm run aih:check -- <sliceId>` | Full computational profile for slice |
| `npm run aih:check -- <sliceId> --profile fast` | Scope + slice-scoped Playwright only |
| `npm run aih:slice:focus -- <id> --reason "..."` | One-shot next-iteration override |
| `npm run aih:slice:reopen -- <id> --reason "..."` | Set `passes: false` + append history |
| `npm run aih:status` | Pending slices, loop override, recent failures |

**Log paths:** `ai-harness/generated/runs/<run-id>-check-<script>.log` and `*-checks.json`

Set `AIH_TEST_STACK_RESET=0` to skip volume teardown on reset (faster local debugging; may retain cross-suite state).

---

## Cross-slice policy

When failures are in tests or modules owned by another slice:

1. Do **not** edit out-of-slice application code or tests.
2. Revert your slice's in-scope uncommitted changes only.
3. Do not touch gate-owned files (`playwright-regression-index.json`, browser-test artifacts).
4. Signal `SLICE_DEFER <owner-slice-id> <reason>` on its own line at the end.

The harness reopens the owner slice, records `history`, and focuses the next loop iteration via `state/loop-state.json`.

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
