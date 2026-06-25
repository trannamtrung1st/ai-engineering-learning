# We Event AI Harness

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

Config lives in `.cursor/mcp.json`. Implementer agents on `frontend` and `test` slices receive `--approve-mcps` automatically. See [`docs/browser-mcp.md`](docs/browser-mcp.md).

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
| `AIH_SKIP_AGENT` | — | Skip implementer (`1`) |
| `AIH_SKIP_REVIEW` | — | Skip AI review (`1`) |
| `AIH_BROWSER_MCP` | — | Enable Playwright MCP on any slice (`1`) |

Defaults live in `ai-harness/config/models.json`.

## Commands

| Command | What it does |
|---|---|
| `npm run aih:once` | **One** iteration (implement → check → review) |
| `npm run aih:loop` | **Autonomous loop** — repeats until all slices pass or max iterations (30) |
| `npm run aih:loop:bg` | Same as loop, but **background/unattended** (nohup + log file) |
| `npm run aih:loop:stop` | Stop background loop |
| `npm run aih:check` | Computational gates only (no agent) |
| `npm run aih:review` | AI review for next pending slice |
| `npm run aih:preview` | **Dev preview** — DB in Docker, API + web as local dev processes |
| `npm run aih:preview:full` | **Full preview** — DB + API + web as built Compose images |
| `npm run aih:preview:verify` | Verify API health + web HTTP 200 (no start) |
| `npm run aih:preview:logs` | View preview logs (combined, api, web, db, stack) |
| `npm run aih:preview:down` | Stop preview stack |

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

The loop picks the next backlog slice, runs the implementer agent, runs checks + AI review, marks pass, commits, and repeats. No manual step between slices.

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

1. `pick-next-slice.sh` selects lowest-priority slice with `passes: false`
2. `build-prompt.sh` injects slice into `implementer.prompt.md`
3. `agent -p --force` implements one slice
4. `run-checks.sh` — computational gates (see below)
5. `run-ai-review.sh` — second agent pass; must end with `REVIEW_PASS`
6. Backlog updated, progress logged, optional git commit

## Computational checks (`npm run aih:check`)

Gates run after every implementer iteration and can be run standalone:

| Gate | When active | Required |
|---|---|---|
| Forbidden patterns (in-memory repos, SQLite, mock data) | `apps/` or `packages/` exists | Yes |
| Slice completion artifacts | Ralph iteration with slice id | Yes |
| `typecheck`, `lint`, `build` | `apps/` exists | Yes — root scripts must exist and pass |
| `test:unit` | `apps/api` exists (and `apps/web` when it defines `test:unit`) | Yes |
| `test:integration` | `apps/api` exists | Yes |
| `test:e2e` | `tests/e2e` exists | Yes |
| Slice `testRequirements` | Ralph iteration with slice id | Yes when field present |
| DB health (Docker Compose) | `docker-compose.yml` exists | Yes when `apps/api` exists |
| Stack startup (API health + web HTTP 200) | `apps/api` and `apps/web` exist | Yes — `verify-stack.sh --quick` via `run-checks.sh`; full poll with `AIH_VERIFY_STACK=1` |

Root `package.json` orchestrates workspace scripts via `npm run <script> -ws --if-present`. Each workspace package (`apps/api`, `apps/web`, `packages/domain`, etc.) must define its own `typecheck`, `lint`, and `build` scripts once bootstrapped.

On a docs-only repo (no `apps/`), `npm run aih:check` passes without code-quality gates.

## Key files

- `ai-harness/whole-app-backlog.json` — slice queue
- `ai-harness/workflows/ralph-loop.json` — loop policy
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
| `COMPLETE` | All slices pass |
| `HUMAN_REVIEW_PASS <id>` | Manual sign-off (merge-ready slices) |

## Specs

Implementation must follow `docs/` — start with `docs/technical/00-system-overview.md` and slice-specific docs from `context-map.json`.
