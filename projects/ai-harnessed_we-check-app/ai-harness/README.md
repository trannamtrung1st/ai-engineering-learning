# We Check AI Harness

Cursor CLI + Ralph loop for spec-driven implementation. Keeps agent prompts thin; policy lives in config files.

## Prerequisites

| Tool | Check | Install |
|---|---|---|
| Cursor CLI | `agent --version` | `curl https://cursor.com/install -fsS \| bash` |
| Auth | `agent login` | OAuth flow — one-time per machine |
| jq | `jq --version` | `brew install jq` |
| curl | `curl --version` | Required for preview startup verification |
| Docker | `docker compose version` | Required when `docker-compose.yml` exists |

`rg` (ripgrep) is optional — checks fall back to `grep` if absent.

### Playwright MCP (frontend/test slices)

One-time setup for browser functional testing:

```bash
npx playwright install chromium
agent mcp enable playwright
```

Config lives in `.cursor/mcp.json` (headless by default). Implementer agents on `frontend` and `test` slices receive `--approve-mcps` for smoke verification; a dedicated **browser test agent** gate runs after computational checks. See [`docs/browser-mcp.md`](docs/browser-mcp.md).

## Auth (no .env file)

```bash
agent login    # browser OAuth — do this once
```

Harness does **not** use a `.env` file. Pass optional overrides on the command line:

```bash
AIH_MODEL=auto npm run aih:loop
AIH_SKIP_AGENT=1 npm run aih:once          # checks only
npm run aih:loop -- 50                     # max 50 iterations
```

| Variable | Default | Purpose |
|---|---|---|
| `AIH_MODEL` | `auto` | Implementer model |
| `AIH_REVIEWER_MODEL` | `auto` | Reviewer model |
| `AIH_TESTER_MODEL` | `auto` | Browser test agent model |
| `AIH_TESTGEN_MODEL` | `auto` | Test case generator model |
| `AIH_AGENT_TIMEOUT_MS` | `3600000` | Max wall time per agent invocation (1 hour); applies to streamed and buffered runs |
| `AIH_AGENT_IDLE_TIMEOUT_MS` | `300000` | Stream idle timeout — no stream-json activity for this long ends the run (5 minutes) |
| `AIH_AGENT_SIGNAL_GRACE_MS` | `15000` | After a completion signal (`SLICE_DONE`, `REVIEW_PASS`, etc.) in agent output, wait this long then terminate the agent process tree |
| `AIH_VERIFY_GATE_TIMEOUT_MS` | `10000` | Shared budget for `verify-stack.sh --gate` when preview supervisors are already running; also `browserTest.previewVerifyGateTimeoutMs` in `ralph-loop.json` |
| `AIH_VERIFY_CURL_CONNECT_TIMEOUT_SEC` | `2` | Per-request curl connect timeout for stack probes |
| `AIH_VERIFY_CURL_MAX_TIME_SEC` | `5` | Per-request curl max time for stack probes |
| `AIH_CHECK_TIMEOUT_MS` | `600000` | Default wall-clock timeout for each computational npm script (10 minutes); kills hung test/build processes |
| `AIH_CHECK_TIMEOUT_<script>_MS` | — | Per-script override (`:` → `_`, e.g. `AIH_CHECK_TIMEOUT_test_integration_MS=1200000`) |
| `AIH_STREAM_AGENT` | `1` | Live stream all harness agent output via stream-json (`0` = legacy buffered text) |
| `AIH_AGENT_VERBOSE` | `1` | Show `[tool]` start/done lines on stderr during streamed agent runs (`0` to disable) |
| `AIH_NO_COLOR` | — | Disable ANSI styling in harness output (`1`) |
| `NO_COLOR` | — | Standard env var; also disables harness styling when set |
| `FORCE_COLOR` | — | Force ANSI styling even when stdout is not a TTY (e.g. under `npm run`) |
| `AIH_SKIP_AGENT` | — | Skip implementer (`1`) |
| `AIH_SKIP_REVIEW` | — | Skip AI review (`1`) |
| `AIH_SKIP_BROWSER_TEST` | — | Skip browser test gate (`1`) |
| `AIH_SKIP_TESTGEN_GATE` | — | Force optional test-case gate (`1`; redundant when `testCaseGate.mode` is `optional`) |
| `AIH_SKIP_TESTGEN_AGENT` | — | Skip testgen agent (`1`) |
| `AIH_BROWSER_MCP` | — | Enable Playwright MCP on any slice (`1`) |
| `AIH_PLAYWRIGHT_MCP_KEEP` | `0` | Newest Playwright MCP files to keep per dir (`0` = wipe before browser slices) |
| `AIH_SKIP_PLAYWRIGHT_MCP_CLEANUP` | — | Skip Playwright MCP artifact cleanup (`1`) |

Defaults live in `ai-harness/config/models.json`.

## Commands

| Command | What it does |
|---|---|
| `npm run aih:once` | **One** iteration (implement → check → browser test → review) |
| `npm run aih:loop` | **Autonomous loop** — repeats until all slices pass or max iterations (30) |
| `npm run aih:loop:bg` | Same as loop, but **background/unattended** (nohup + log file) |
| `npm run aih:loop:stop` | Stop background loop |
| `npm run aih:check` | Computational gates only (no agent) |
| `npm run aih:browser-test` | Playwright MCP functional test for next/current slice |
| `npm run aih:review` | AI review for next pending slice |
| `npm run aih:preview` | **Dev preview** — DB in Docker, API + web as local dev processes |
| `npm run aih:preview:full` | **Full preview** — DB + API + web as built Compose images |
| `npm run aih:preview:verify` | Verify API health + web HTTP 200 (no start) |
| `npm run aih:preview:logs` | View preview logs (combined, api, web, db, stack) |
| `npm run aih:preview:down` | Stop preview stack |
| `npm run aih:playwright-mcp:clean` | Remove Playwright MCP page snapshots and console logs |
| `npm run aih:testgen:once` | Generate test cases for one slice from docs |
| `npm run aih:testgen:loop` | Autonomous TestGen loop until all slices have current test cases |
| `npm run aih:testgen:enhance` | Ad-hoc improve test cases for one tag with free-text instructions |
| `npm run aih:testgen:drift` | Detect doc drift; reset passes + test case state |
| `npm run aih:testgen:validate` | Validate generated test case JSON for a slice |

### Preview (API + web)

Start and verify both API and web. Canonical spec: [`ai-harness/docs/preview-runtime.md`](docs/preview-runtime.md).

```bash
# Dev mode (default) — fast reload
npm run aih:preview

# Full preview — production-like containers (requires Dockerfiles)
npm run aih:preview:full

# Verify an already-running stack
npm run aih:preview:verify

# View logs (combined stream or per-service)
npm run aih:preview:logs
npm run aih:preview:logs -- --follow

# Tear down
npm run aih:preview:down
```

Startup success requires API `GET /api/v1/health` with `status=ok` and `db=connected`, and web `GET /` returning HTTP 200. See preview-runtime doc for timeouts and script contract.

### Recommended workflow

Ralph and TestGen can run in parallel — implementation does not require test cases upfront (default `testCaseGate.mode: optional` in `ralph-loop.json`):

```bash
# Option A: parallel — implement while TestGen catches up
npm run aih:loop &
npm run aih:testgen:loop

# Option B: TestGen first (strict mode — set testCaseGate.mode to "required" in ralph-loop.json)
npm run aih:testgen:loop
npm run aih:loop

# After editing docs — drift check resets passes; regenerate test cases
npm run aih:testgen:drift && npm run aih:testgen:loop
```

To re-run implementer and tester gates after TestGen catches up, set `passes: false` on that slice in `whole-app-backlog.json`.

### Autonomous loop (hands-off)

**One-time auth**, then run:

```bash
agent login
npm run aih:loop:bg
tail -f ai-harness/generated/runs/loop.log
```

**Foreground** (terminal stays open):

```bash
npm run aih:loop
# or with overrides:
AIH_MODEL=auto npm run aih:loop -- 50
```

**Stop background loop:**

```bash
npm run aih:loop:stop
```

The loop picks the next backlog slice, runs the implementer agent, runs checks + browser test (frontend/test slices) + AI review, marks pass, commits, and repeats. No manual step between slices.

### First run

```bash
agent login
npm run aih:check          # should pass on docs-only repo
npm run aih:once             # runs implementer on first backlog slice
```

### Debug without agent (checks only)

```bash
AIH_SKIP_AGENT=1 AIH_SKIP_REVIEW=1 npm run aih:once
```

### Review a specific slice

```bash
./ai-harness/scripts/run-ai-review.sh module-registration
```

## Flow

### TestGen (before implementation)

1. Pick next requirement tag from backlog `acceptance` union where `test-case-index.json` is not current
2. `check-test-case-drift.sh` compares doc fingerprint (from `testgen-docs-map.json`) per tag
3. `build-prompt.sh testgen <tag>` injects into `testgen.prompt.md`
4. `agent -p --force` writes `docs/test-cases/items/<tag>.json`
5. `validate-test-cases.sh` — schema + traceability
6. `sync-test-cases-to-backlog.sh` — updates slices whose `acceptance` includes the tag
7. Tag marked current in `test-case-index.json`; optional git commit (TestGen-owned paths only — test case artifact, index, backlog sync, progress)

**Ad-hoc enhance** (`npm run aih:testgen:enhance`) — improve cases for one tag without waiting for doc drift:

```bash
# Positional instructions
npm run aih:testgen:enhance -- FR-08 "Add browser-journey cases for admin pagination and sort"

# Stdin
echo "Tighten preconditions on TC-FR-08-003" | npm run aih:testgen:enhance -- FR-08

# Options: --file <path>, --context <path1,path2>, --no-commit
npm run aih:testgen:enhance -- FR-08 --no-commit --context docs/ui-ux/14-listing-pages-search-filter-sort.md "Add sort cases"
```

The script reuses the TestGen agent and validation pipeline; it attaches docs, related backlog slices, and existing artifact summary automatically. Set `AIH_TESTGEN_NO_COMMIT=1` to skip commit (same as `--no-commit`).

### Implementation

1. `pick-next-slice.sh` selects lowest-priority slice with `passes: false`
2. Doc drift check — fails if any referenced tag has stale test-case state
3. Test case gate — **optional by default** (`testCaseGate.mode` in `ralph-loop.json`); warns and continues when tags are missing; hard-fails only in `required` mode
4. `build-prompt.sh` injects slice into `implementer.prompt.md` (plus prior checks / browser-test / AI-review failures when the slice failed those gates last time)
5. `agent -p --force` implements one slice
6. `run-checks.sh` — computational gates (see below)
7. `run-browser-test.sh` — Playwright MCP gate using generated browser cases; must end with `BROWSER_TEST_PASS`
8. `run-ai-review.sh` — static code review; must end with `REVIEW_PASS`
9. Backlog updated (`passes: true`), progress logged, optional git commit

## Computational checks (`npm run aih:check`)

Gates run after every implementer iteration and can be run standalone:

| Gate | When active | Required |
|---|---|---|
| Forbidden patterns (in-memory repos, SQLite, mock data) | `apps/` or `packages/` exists | Yes |
| Slice completion artifacts | Ralph iteration with slice id | Yes |
| `typecheck`, `lint`, `build` | `apps/` exists | Yes — root scripts must exist and pass; each has a wall-clock timeout (default 10m, integration/e2e 15m) |
| `test:unit` | `apps/api` exists (and `apps/web` when it defines `test:unit`) | Yes |
| `test:integration` | `apps/api` exists | Yes |
| `test:e2e` | `tests/e2e` exists | Yes |
| Slice `testRequirements` | Ralph iteration with slice id | Yes when field present |
| Generated test case coverage | all slice `acceptance` product items current | Yes — integration/e2e case tags must appear in test files (unit is implementer-owned via `testRequirements`) |
| DB health (Docker Compose) | `docker-compose.yml` exists | Yes when `apps/api` exists |
| Stack startup (API health + web HTTP 200) | `apps/api` and `apps/web` exist | Yes — `verify-stack.sh --quick` via `run-checks.sh`; full poll with `AIH_VERIFY_STACK=1` |

Root `package.json` orchestrates workspace scripts via `npm run <script> -ws --if-present`. Each workspace package (`apps/api`, `apps/web`, `packages/domain`, etc.) must define its own `typecheck`, `lint`, and `build` scripts once bootstrapped.

On a docs-only repo (no `apps/`), `npm run aih:check` passes without code-quality gates.

## Key files

- `ai-harness/whole-app-backlog.json` — slice queue
- `ai-harness/workflows/ralph-loop.json` — loop policy (`testCaseGate.mode`)
- `ai-harness/workflows/testgen-loop.json` — TestGen loop policy
- `ai-harness/config/testgen-docs-map.json` — doc resolution rules per requirement tag
- `ai-harness/test-case-index.json` — slim generation state (current, fingerprint)
- `docs/test-cases/items/` — generated test case artifacts per tag
- `ai-harness/config/context-map.json` — which docs to read per slice
- `ai-harness/state/guardrails.md` — lessons (Ralph Signs)
- `ai-harness/HARNESS-DESIGN.md` — component index
- `ai-harness/docs/preview-runtime.md` — preview + startup verification spec
- `ai-harness/docs/browser-mcp.md` — Playwright MCP functional testing

## Signals

| Signal | Meaning |
|---|---|
| `SLICE_DONE <id>` | Implementer finished |
| `SLICE_BLOCKED <reason>` | Blocked |
| `REVIEW_PASS` / `REVIEW_FAIL` | AI review outcome |
| `BROWSER_TEST_PASS` / `BROWSER_TEST_FAIL` | Browser functional test outcome |
| `TESTGEN_DONE <id>` / `TESTGEN_BLOCKED <reason>` | Test case generation outcome |
| `TESTGEN_COMPLETE` | All slices have current test cases |
| `COMPLETE` | All slices pass |
| `HUMAN_REVIEW_PASS <id>` | Manual sign-off (merge-ready slices) |

## Specs

Implementation must follow `docs/` — start with `docs/technical/00-system-overview.md` and slice-specific docs from `context-map.json`.
