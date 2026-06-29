# Browser MCP — Playwright functional testing

Interactive UI verification for frontend and test slices. The harness uses Playwright MCP in two places:

1. **Implementer smoke test** — `frontend`/`test` slices get `--approve-mcps` during implementation
2. **Browser test agent gate** — `run-browser-test.sh` runs after computational checks and before AI code review (hard gate for `frontend`/`test` slices). When a prior browser test failed for the slice and `browserTest.retryFailedCasesFirst` is true (default), the harness runs a **retry phase** (failed case IDs only, fail-fast) then a **full phase** (all `layer: browser` cases) before accepting `BROWSER_TEST_PASS`.

## Phased browser test gate

When the latest failed `*-browser-test.txt` for the slice contains parseable `TC-*: FAIL` lines:

1. **Retry phase** — tester agent runs only those case IDs; exits on first failure without running the full suite
2. **Full phase** — tester agent runs every mandatory browser case to confirm no regressions

Artifacts: `*-browser-test-retry.txt`, `*-browser-test-full.txt`, combined `*-browser-test.txt`, and `*-browser-test.json` with a `phases` array. Set `browserTest.retryFailedCasesFirst` to `false` in `ralph-loop.json` to disable and always run full phase only.

## Prerequisites

| Step | Command |
|---|---|
| Install Chromium (one-time) | `npx playwright install chromium` |
| Approve MCP for headless loop | `agent mcp enable playwright` |
| Start preview stack | `npm run aih:preview` |
| Verify stack | `npm run aih:preview:verify` |

Project MCP config: [`.cursor/mcp.json`](../../.cursor/mcp.json) — writes snapshots to `ai-harness/generated/runs/playwright-mcp` (gitignored). `--headless` is enabled by default for unattended loops; remove it from `.cursor/mcp.json` for local visual debugging.

## Artifact cleanup

Playwright MCP writes timestamped page snapshots (`.yml`) and console logs. The harness cleans these automatically before each implementer run on `frontend`/`test` slices (or when `AIH_BROWSER_MCP=1`), and before each browser test agent gate run.

| Command / env | Behavior |
|---|---|
| (default) | Wipe all Playwright MCP artifacts before browser slices |
| `npm run aih:playwright-mcp:clean` | Manual cleanup of `.playwright-mcp/` and `ai-harness/generated/runs/playwright-mcp/` |
| `AIH_PLAYWRIGHT_MCP_KEEP=20` | Keep the 20 newest files per directory instead of wiping |
| `AIH_SKIP_PLAYWRIGHT_MCP_CLEANUP=1` | Disable automatic cleanup (debugging) |

## Playwright MCP vs built-in browser

| Tool | Use when |
|---|---|
| **Playwright MCP** (`playwright` server) | Functional flows, accessibility snapshots, form interaction, pagination navigation |
| **cursor-ide-browser** (IDE built-in) | Ad-hoc inspection in Cursor IDE sessions |

Prefer Playwright MCP during harness implementer runs on frontend/test slices.

## Visual UI/UX verification (screenshots)

Accessibility snapshots help with structure and interaction; **screenshots** are required for visual UI/UX review.

### Canonical screenshot paths (required)

All agent UI screenshots go under `ai-harness/generated/runs/screenshots/` (gitignored):

| Agent | Directory |
|---|---|
| **Implementer** | `ai-harness/generated/runs/screenshots/<slice-id>/implementer/` |
| **Browser test agent** | `ai-harness/generated/runs/screenshots/<slice-id>/browser-test/` |

- Create the directory with `mkdir -p` before the first capture (the harness pre-creates it when the agent starts)
- **cursor-ide-browser:** `browser_take_screenshot` → set `filename` to an absolute path in that directory
- **Playwright MCP:** use the same directory when supported; otherwise move/copy files here after capture
- **Do not** save to repo root, `/tmp`, `.playwright-mcp/`, or other random paths
- Filename: `<UTC-timestamp>-<page-or-case-slug>.png` (e.g. `20250629T120000Z-check-in.png`)

| Agent | When to screenshot |
|---|---|
| **Implementer** | Every page/route created or modified in the slice — before `SLICE_DONE`, even when flows pass |
| **Browser test agent** | Each distinct page visited when verifying browser cases — especially layout, forms, tables, badges, and state variants |

Compare against `docs/ui-ux/00-production-ui-quality-bar.md`. Fix obvious UI issues during implementation; report UI-quality FAILs during the browser test gate.

## Agent timeout discipline

Implementer smoke tests and the browser test gate can hang on stuck pages, permissions, or deadlocked UI. **Agents must apply wall-clock limits themselves** — do not wait indefinitely.

| Agent | Limit | On timeout |
|---|---|---|
| **Implementer (browser smoke)** | **30s** per navigation/action | Stop automation, note URL/state, fix or `SLICE_BLOCKED` |
| **Browser test agent** | **30s** per case step; **15 min** whole pass | FAIL case or emit `BROWSER_TEST_FAIL` |
| **Implementer (npm checks)** | Budgets in `ralph-loop.json` — prefer `npm run aih:check -- <slice-id>` | Kill process tree; fix deadlock before `SLICE_DONE` |

See implementer/tester prompts for full rules. Computational timeouts are enforced automatically by `run-checks.sh`; browser timeouts are agent-enforced.

## Standard flows

### Participant

1. Open `http://localhost:3000`
2. Browse paginated events — confirm prev/next controls and page changes
3. Open event detail → register → confirm status badge
4. My registrations — confirm paginated list loads without N+1 errors
5. Check-in and feedback flows when in scope for the slice

### Organizer

1. Open organizer event list — paginated table
2. Create or edit event
3. Dashboard, check-in console, registrations/eligibility tables

Use dev auth tokens or the app's dev login flow as documented in `docs/technical/10-local-development-setup.md`.

## What the harness automates vs agent-driven

| Layer | Mechanism |
|---|---|
| Unit tests | `npm run test:unit` — validators, component tests |
| Integration tests | `npm run test:integration` — API + Postgres |
| API scenario tests | `npm run test:e2e` — in-process Fastify flows |
| HTTP stack probe | `verify-stack.sh` — health + web HTTP 200 |
| **Browser UI (implementer)** | Playwright MCP smoke test during implementation |
| **Browser UI (gate)** | `run-browser-test.sh` — dedicated test agent; must emit `BROWSER_TEST_PASS` when all runnable cases pass |

### Out-of-scope case results

Cases that require physical devices or are not applicable in Playwright MCP must be reported as `SKIP`, not `FAIL`:

- `TC-…: SKIP — physical-device — <reason>`
- `TC-…: SKIP — not-applicable — <reason>`

Skipped cases are excluded from pass/fail — only `FAIL` lines block the gate.

API-level e2e remains the automated acceptance gate. Playwright MCP supplements with real rendered UI verification; the browser test agent gate enforces it before code review.

## On completion

Append one line to `ai-harness/state/progress.md`:

```
<timestamp> | <slice-id> | browser_verified: <brief flow exercised>
```

## Troubleshooting

| Issue | Fix |
|---|---|
| MCP not available | Run `agent mcp list`; enable with `agent mcp enable playwright` |
| Web unreachable | `npm run aih:preview` then `npm run aih:preview:verify` |
| Stale Next cache | `npm run aih:preview:down`; `rm -rf apps/web/.next`; `npm run aih:preview` (separate commands — never pipe preview through `tail`) |
| Loop stuck after `SLICE_DONE` | Orphaned shell from `aih:preview \| tail` — run preview commands separately; harness now auto-terminates the agent process tree after completion signals |
| Loop stuck at `starting dev preview` | Fixed: background supervisors/log followers no longer inherit stdout (was blocking browser-test gate); restart loop to pick up fix |
| Force MCP on implementer for any slice | `AIH_BROWSER_MCP=1 npm run aih:once` |
| Skip browser test gate | `AIH_SKIP_BROWSER_TEST=1 npm run aih:once` |
| Run browser test only | `npm run aih:browser-test -- <slice-id>` |

## Related docs

- [`preview-runtime.md`](preview-runtime.md) — preview stack and HTTP probes
- [`../README.md`](../README.md) — harness commands and env vars
- `docs/technical/11-testing-plan.md` — test pyramid and acceptance matrix
