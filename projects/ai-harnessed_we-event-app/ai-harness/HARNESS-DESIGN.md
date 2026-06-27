# AI Harness Design — We Event

Concise index for the 12 harness components. Referenced by `docs/technical/13-docker-compose-local-runtime.md`.

## Component map

| Component | Location |
|---|---|
| Model | `config/models.json`, env `AIH_MODEL` |
| Prompt | `agents/implementer.prompt.md`, `agents/tester.prompt.md`, `agents/reviewer.prompt.md`, `agents/testgen.prompt.md` |
| Context | `config/context-map.json` — doc pointers per slice/agent |
| Tools | Cursor CLI (`agent -p --force`) + Playwright MCP on frontend/test slices |
| Workflow | `workflows/ralph-loop.json`, `workflows/testgen-loop.json` |
| Memory/State | `state/progress.md`, `state/guardrails.md`, `whole-app-backlog.json` (in `ai-harness/`) |
| Test cases | `config/testgen-docs-map.json`, `test-case-index.json`, `docs/test-cases/items/<tag>.json` |
| Validation | `scripts/run-checks.sh` — layered tests; `scripts/run-browser-test.sh` — Playwright MCP gate |
| TestGen | `scripts/testgen-loop.sh`, `scripts/check-test-case-drift.sh` — docs-driven catalog per requirement tag |
| Guardrails | `state/guardrails.md` + forbidden patterns in `ralph-loop.json` |
| Observability | `generated/runs/<timestamp>-*.json` |
| Feedback loops | Failed check/browser-test/review → guardrails append → retry; prior checks, browser-test, and review output injected into next implementer prompt |
| Human review | `workflows/human-review-checklist.md` |
| Preview runtime | `scripts/preview-stack.sh`, `docs/preview-runtime.md` |
| Browser MCP | `.cursor/mcp.json`, `docs/browser-mcp.md` |
| Startup verification | `scripts/verify-stack.sh` |
| Runtime | `ralph-loop.json` → `runtimeValidation` (db, api, web) |
| Agent timeout | `ralph-loop.json` / `testgen-loop.json` → `agent.idleTimeoutMs` (default 5m stream idle), `agent.timeoutMs` (default 1h max wall), `agent.signalGraceMs` / `agent.resultGraceMs` (early exit after completion signals / result event); override `AIH_AGENT_IDLE_TIMEOUT_MS` / `AIH_AGENT_TIMEOUT_MS` / `AIH_AGENT_SIGNAL_GRACE_MS` / `AIH_AGENT_RESULT_GRACE_MS` |

## Ralph loop

Each iteration spawns a **fresh** agent context (no `--resume`). State lives on disk and in git.

```
pick slice → drift check → test-case gate (optional) → agent implement → run-checks → run-browser-test → run-ai-review → mark pass → commit
```

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

TestGen emits only `integration`, `e2e`, and `browser` layers in generated artifacts; unit tests are the implementer's responsibility via `testRequirements.unit` and colocated `*.test.ts` files.

Doc drift (`check-test-case-drift.sh`) resets tag state in `test-case-index.json` and `passes` on all slices whose `acceptance` references that tag.

Ralph and TestGen can run independently. Set `testCaseGate.mode` to `required` in `ralph-loop.json` to restore the strict TestGen-first workflow.

## Backlog

`ai-harness/whole-app-backlog.json` — phased slices with `passes`, `priority`, `acceptance`, `completionArtifacts`. Set `passes: false` to re-queue a slice for another Ralph iteration.

## Persistence policy

Harness hard-fails: in-memory repos, SQLite, mock page data, lorem ipsum. See `ralph-loop.json` → `forbiddenPatterns`.

## DB runtime (when compose exists)

```json
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
    "url": "http://localhost:3000",
    "expectStatus": 200,
    "timeoutMs": 120000
  }
}
```

`run-checks.sh` enforces `db` and quick stack probes. Full stack poll via `AIH_VERIFY_STACK=1` or `npm run aih:preview:verify`.

Dev mode: DB in Docker; API/web as local Node processes per `docs/technical/13-docker-compose-local-runtime.md`. Full preview: all services via Compose `full-preview` profile.
