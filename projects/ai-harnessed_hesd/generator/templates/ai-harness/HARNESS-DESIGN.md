# AI Harness Design

Concise index for the 12 harness components. Referenced by `docs/technical/13-docker-compose-local-runtime.md`.

## Component map

| Component | Location |
|---|---|
| Model | `config/models.json`, env `AIH_MODEL` |
| Prompt | `agents/implementer.prompt.md`, `agents/tester.prompt.md`, `agents/reviewer.prompt.md`, `agents/testgen.prompt.md` |
| Context | `config/context-map.json` — doc pointers per slice/agent |
| Skills | `skills/*/SKILL.md` — agent craft guidance (`visual-design`, `ui-ux-testing`); wired via `context-map.json` `alwaysRead`, injected into prompts by `build-prompt.sh` |
| Tools | Cursor CLI (`agent -p --force`) + Playwright MCP on frontend/test slices |
| Workflow | `workflows/ralph-loop.json`, `workflows/testgen-loop.json` |
| Memory/State | `state/progress.md`, `state/guardrails.md`, `state/loop-state.json` (one-shot next slice override), `whole-app-backlog.json` (slice `history` for reopen/failure context) |
| Test cases | `config/testgen-docs-map.json`, `test-case-index.json`, `docs/test-cases/items/<tag>.json` |
| Playwright regression | `playwright-regression-index.json`, `tests/playwright-ui/scenarios/`, `docs/playwright-regression.md` |
| UX bugs | `generated/runs/ux-bugs/<slice>/<run>.json`, `docs/ux-bug-logging.md`, `skills/ui-ux-testing/SKILL.md` |
| Test failure triage | `docs/test-failure-triage.md` — integration/e2e flake decision tree, cross-slice deferral |
| Validation | `scripts/run-checks.sh` — layered tests; `scripts/run-browser-test.sh` — Playwright MCP gate |
| TestGen | `scripts/testgen-loop.sh`, `scripts/check-test-case-drift.sh` — docs-driven catalog per requirement tag |
| Guardrails | `state/guardrails.md` + forbidden patterns in `ralph-loop.json` |
| Observability | `generated/runs/<timestamp>-*.json` — TTL-pruned each Ralph iteration (`loop.generatedRetentionMinutes`, default 60m; preview/loop runtime files excluded) |
| Feedback loops | Failed scope/check/browser-test/review → guardrails append → retry; prior scope, checks (JSON + **log excerpts** with scope hints), browser-test, and review output injected into next implementer prompt; browser tester retries failed cases first (fail-fast) then full suite (`browserTest.retryFailedCasesFirst`) |
| Human review | `workflows/human-review-checklist.md` |
| Preview runtime | `scripts/preview-stack.sh`, `docs/preview-runtime.md` |
| Browser MCP | `.cursor/mcp.json`, `docs/browser-mcp.md` |
| Startup verification | `scripts/verify-stack.sh` |
| Runtime | `ralph-loop.json` → `runtimeValidation` (db, api, web) |
| Agent timeout | `ralph-loop.json` / `testgen-loop.json` → `agent.idleTimeoutMs` (default 5m stream idle), `agent.timeoutMs` (default 1h max wall), `agent.signalGraceMs` / `agent.resultGraceMs` (early exit after completion signals / result event); override `AIH_AGENT_IDLE_TIMEOUT_MS` / `AIH_AGENT_TIMEOUT_MS` / `AIH_AGENT_SIGNAL_GRACE_MS` / `AIH_AGENT_RESULT_GRACE_MS` |
| Computational check timeout | `ralph-loop.json` → `computationalChecks.commandTimeoutMs` (default 10m) and `commandTimeouts` per npm script; override `AIH_CHECK_TIMEOUT_MS` or `AIH_CHECK_TIMEOUT_<script>_MS`; on timeout the harness kills the process tree and records `timedOut: true` in the checks report |
| Check logs + heartbeats | `run-checks.sh` / `run-logged-check.sh` write per-script logs to `ai-harness/generated/runs/<run-id>-check-<script>.log` and print `still running` every 30s; agent stream idle timeout is suspended while a shell tool runs |
| UI screenshots | `ai-harness/generated/runs/screenshots/<slice-id>/implementer/` or `.../browser-test/` — agents must save all captures here (injected into prompts via `build-prompt.sh`); contrast/padding checklist in `docs/ui-visual-verification.md` |

## Ralph loop

Each iteration spawns a **fresh** agent context (no `--resume`). State lives on disk and in git.

```
pick slice (priority, or one-shot override from loop-state.json) → drift check → test-case gate → agent implement → slice scope gate → run-checks → run-browser-test → run-ai-review → mark pass → commit
```

**Slice selection:** pending slices (`passes: false`) sorted by `priority`. Optional one-shot override in `state/loop-state.json` (`nextSliceId`) — consumed on pick so the next iteration focuses a specific slice, then normal priority resumes.

**Slice history:** each backlog slice may have a `history` array (`at`, `kind`, `reason`, `source`, optional `relatedSlice`). Harness appends on gate failures; humans use `npm run aih:slice:reopen`; implementer `SLICE_DEFER` reopens the owner slice and redirects the next iteration.

**Cross-slice deferral:** implementer signals `SLICE_DEFER <owner-slice-id> <reason>` after reverting in-scope changes. Harness reopens the owner, records history, sets loop override, and exits the iteration.

Test case gate policy (`ralph-loop.json` → `testCaseGate.mode`):

| Value | Behavior |
|---|---|
| `optional` (default) | Warn and continue when acceptance tags lack current test cases |
| `required` | Hard-fail until all slice acceptance tags are current |

To re-run a slice after TestGen catches up, set `passes: false` manually in `whole-app-backlog.json`.

Scripts: `ralph-loop.sh` (autonomous), `ralph-once.sh` (single step).

## TestGen loop

Separate loop that generates structured test cases from slice docs (can run in parallel with Ralph):

```
pick requirement tag (from backlog acceptance union) → doc fingerprint → testgen agent → validate JSON → sync slice metadata → mark tag in test-case-index → commit
```

Scripts: `testgen-loop.sh` (autonomous), `testgen-once.sh` (single step).

`testgen-loop.json` → `validation.categoryPolicy` allows per-tag overrides of `minCasesPerCategory` (e.g. `NFR-*` relaxes the functional minimum to 0).

TestGen emits only `integration`, `e2e` (API), and `browser` (MCP checklist) layers in generated artifacts; unit tests are the implementer's responsibility via `testRequirements.unit` and colocated `*.test.ts` files. Executable Playwright UI specs in `tests/playwright-ui/scenarios/` are generated by the browser test agent — tracked in `playwright-regression-index.json`.

Doc drift (`check-test-case-drift.sh`) resets tag state in `test-case-index.json` and `passes` on all slices whose `acceptance` references that tag.

Ralph and TestGen can run independently. Set `testCaseGate.mode` to `required` in `ralph-loop.json` to restore the strict TestGen-first workflow.

## Backlog

`ai-harness/whole-app-backlog.json` — phased slices with `passes`, `priority`, `acceptance`, `completionArtifacts`. Set `passes: false` to re-queue a slice, or use `npm run aih:slice:reopen`. Optional per-slice `history` records why a slice was reopened or failed (injected into implementer prompts).

`ai-harness/state/loop-state.json` — optional one-shot `nextSliceId` override for the next Ralph iteration (`npm run aih:slice:focus`).

## Persistence policy

Harness hard-fails: in-memory repos, SQLite, mock page data, lorem ipsum. See `ralph-loop.json` → `forbiddenPatterns`.

## DB runtime (when compose exists)

```json
"computationalChecks": {
  "commandTimeoutMs": 600000,
  "commandTimeouts": {
    "typecheck": 300000,
    "lint": 300000,
    "build": 600000,
    "test:unit": 600000,
    "test:integration": 900000,
    "test:e2e": 900000,
    "test:playwright-ui": 900000
  },
  "runtimeValidation": {
  "db": {
    "strategy": "docker-compose",
    "service": "db",
    "healthTimeoutMs": 60000,
    "requiredBeforeApi": true,
    "activeWhen": "docker-compose.yml"
  },
  "api": {
    "activeWhen": "apps/api",
    "url": "http://localhost:3001/api/v1/health",
    "expectJson": { "status": "ok", "db": "connected" },
    "timeoutMs": 60000
  },
  "web": {
    "activeWhen": "apps/web",
    "url": "http://localhost:3007",
    "expectStatus": 200,
    "timeoutMs": 120000
  },
  "testStack": {
    "composeFile": "docker-compose.test.yml",
    "projectName": "<slug>-test",
    "services": ["db"],
    "activeWhen": "docker-compose.test.yml",
    "env": {
      "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/app_test"
    }
  }
}
```

`run-checks.sh` resets the **test stack** before integration/e2e when `docker-compose.test.yml` exists; preview dev DB (`docker-compose.yml`) is not auto-started for those gates. Scripts: `aih:test:stack:up`, `aih:test:stack:reset`, `aih:test:stack:down` (`test-stack.sh`).

**Test isolation:** Integration suites that start background schedulers must clean up in `afterEach` (see `docs/test-failure-triage.md`). Full-suite-only failures often indicate leaked in-process timers, not DB state alone.

`run-checks.sh` enforces test stack health and quick stack probes. Full stack poll via `AIH_VERIFY_STACK=1` or `npm run aih:preview:verify`.

**Scenario probe:** By default `verify-scenarios.sh` SKIPs when `ai-harness/config/scenario-probe.json` is absent. Add that file (generated by harness planner or manually) to define curl steps for a canonical API smoke flow — dev token plus authenticated GET, etc. Schema: `ai-harness/config/scenario-probe.schema.json`.

Dev mode: DB in Docker; API/web as local Node processes per `docs/technical/13-docker-compose-local-runtime.md`. Full preview: all services via Compose `full-preview` profile.
