# Performance smoke runbook

**Slice:** `test-nfr-performance-reliability-smoke`  
**Related:** [11-testing-plan.md](./11-testing-plan.md) §7.1 · [07-non-functional-risk.md](../brds/07-non-functional-risk.md)

## Purpose

This runbook explains how to run, read, and triage Attendly performance smoke tests that guard AC-20, AC-21, AC-22, NFR-01, NFR-03, and NFR-16 baselines during class-start peaks.

## Smoke profile

| Dimension | Target | Gate function |
| --- | --- | --- |
| Median check-in latency | < 30s (AC-20, NFR-01) | `evaluateMedianLatencyGate` |
| Valid processing success rate | >= 99% (AC-22, NFR-03) | `evaluateSuccessRateGate` |
| Majority completion window | > 50% within 5 min of open (AC-21, NFR-02) | `evaluateMajorityCompletionGate` |
| Operational telemetry | SessionOpened, QrTokenIssued, CheckInAttemptRecorded (NFR-16) | integration telemetry snapshot |

Representative load: **2 open sessions × 20 enrolled students** (40 concurrent rule-pass check-ins with concurrency 5), GPS-off policies, isolated `PERF-*` fixture hierarchy.

## Local execution

Reset the compose test stack, then run the smoke suite:

```bash
npm run aih:test:stack:reset
npm run test:integration:performance-smoke
npm run test:e2e -- performance-smoke
```

Publish metric JSON for triage (written under `ai-harness/generated/runs/performance-smoke/`):

```bash
PERF_SMOKE_PUBLISH_METRICS=true npm run test:integration:performance-smoke
```

Full harness gate (slice scope + timeouts):

```bash
npm run aih:check -- test-nfr-performance-reliability-smoke
```

## Interpreting metric snapshots

Each snapshot includes:

- `verdicts.medianCheckInMs` — median server-side round-trip for successful check-ins in milliseconds
- `verdicts.validSuccessRate` — ratio of rule-pass requests that returned HTTP 200 Success
- `verdicts.majorityCompletionRate` — enrolled students with Present/Late within the 5-minute window
- `overallPass` — all verdicts passed

### PASS criteria

- `medianCheckInMs.actual` **strictly below** 30000
- `validSuccessRate.actual` **>=** 0.99
- `majorityCompletionRate.actual` **>** 0.5

### FAIL triage

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| Median latency near or above 30s | DB contention, missing indexes, API saturation | Inspect API logs, Postgres slow queries, rerun isolated burst |
| Success rate 95–98% | transient 5xx, connection pool exhaustion | Check health endpoint, pool size, retry idempotency behavior |
| Success rate < 95% | functional regression in check-in path | Run `test:integration:critical` and check-in module tests |
| Majority completion fails with high latency pass | enrollment fixture drift or session not Open | Verify session open timestamps and enrollment counts |
| Telemetry gaps | realtime gateway not publishing | Inspect `getOperationalTelemetrySnapshot` and M09 integration tests |

Rule-fail outcomes (ExpiredQr, DuplicateCheckIn, SessionClosed) are **excluded** from the valid-request denominator per NFR-03.

## CI artifacts

The `integration-performance-smoke` workflow job:

1. Migrates and seeds the test database
2. Runs `npm run test:integration:performance-smoke` with `PERF_SMOKE_PUBLISH_METRICS=true`
3. Uploads `ai-harness/generated/runs/performance-smoke/*.json` on every run

Use uploaded JSON to compare regressions across PRs without re-running load locally.

## Physical pilot (out of harness scope)

TC-AC-20-008, TC-AC-21-010, and TC-NFR-16-016 require physical campus devices — skip in CI; document pilot evidence separately.

## Preview ITAdmin (TC-NFR-16-015)

Browser smoke uses `e2e-itadmin@attendly.local` (Institution-scoped ITAdmin). The performance smoke fixture `ensureItAdminPreviewActor` seeds this actor on the test stack; preview stacks that lack the user can run integration smoke once or apply the same fixture against the preview database before browser gates.

ITAdmin audit list queries require institution-wide technical scope resolution — empty section scope previously returned `OutOfScope` before the ITAdmin audit view could load.

When preview exhausts Scheduled seed sessions, run `npm run db:seed:preview-sessions` (or rely on Playwright support auto-refresh via `apps/api/scripts/preview-session-refresh.mjs`).

Browser cases marked `harnessSkip: physical-device` (campus Wi-Fi, iOS Safari, Android Chrome) require staging pilot evidence documented separately per testing-plan §6.2.
