# Browser MCP — Playwright functional testing

Interactive UI verification for frontend and test slices. The harness uses Playwright MCP in two places:

1. **Implementer smoke test** — `frontend`/`test` slices get `--approve-mcps` during implementation
2. **Browser test agent gate** — `run-browser-test.sh` runs after the slice scope gate and computational checks, before AI code review (hard gate for `frontend`/`test` slices). When a prior browser test failed for the slice and `browserTest.retryFailedCasesFirst` is true (default), the harness runs a **retry phase** (failed case IDs only, fail-fast) then a **full phase** (all `layer: browser` cases) before accepting `BROWSER_TEST_PASS`.

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
- Filename: `<UTC-timestamp>-<page-or-case-slug>.png` (e.g. `20250629T120000Z-login.png`)

| Agent | When to screenshot |
|---|---|
| **Implementer** | Every page/route created or modified in the slice — before `SLICE_DONE`, even when flows pass |
| **Browser test agent** | Each distinct page visited when verifying browser cases — especially layout, forms, tables, badges, and state variants |

Compare against `docs/ui-ux/00-production-ui-quality-bar.md` and [ui-visual-verification.md](./ui-visual-verification.md). Fix obvious UI issues during implementation; report UI-quality FAILs during the browser test gate.

### Visual contrast review (screenshots over snapshots)

**Screenshots** are required for contrast, padding, and layout craft. **Accessibility snapshots** help structure and interaction only — do not rely on them to judge button label readability or padding.

Per modified route, implementer captures **320×568** and **1280×720** screenshots and runs the checklist in [ui-visual-verification.md](./ui-visual-verification.md) before `SLICE_DONE`. Browser tester applies the same checklist when reviewing craft FAILs.

## Agent timeout discipline

Implementer smoke tests and the browser test gate can hang on stuck pages, permissions, or deadlocked UI. **Agents must apply wall-clock limits themselves** — do not wait indefinitely.

| Agent | Limit | On timeout |
|---|---|---|
| **Implementer (browser smoke)** | **30s** per navigation/action | Stop automation, note URL/state, fix or `SLICE_BLOCKED` |
| **Browser test agent** | **30s** per case step; **15 min** whole pass | FAIL case or emit `BROWSER_TEST_FAIL` |
| **Implementer (npm checks)** | Budgets in `ralph-loop.json` — prefer `npm run aih:check -- <slice-id>` | Kill process tree; fix deadlock before `SLICE_DONE` |

See implementer/tester prompts for full rules. Computational timeouts are enforced automatically by `run-checks.sh`; browser timeouts are agent-enforced.

## Standard flows

Derive flows from `docs/ui-ux/10-user-flows.md` and `docs/technical/01-roles-permissions.md`. Below are role-agnostic patterns for the two primary actors (substituted from product metadata at scaffold time).

### Student

1. Open `http://localhost:3007`
2. Browse paginated listing pages — confirm prev/next controls and page changes
3. Open detail view → complete primary action → confirm status or outcome badge
4. My-items or account-scoped lists — confirm paginated list loads without N+1 errors
5. Workflow-specific flows when in scope for the slice (per user-flows doc)

### Lecturer

1. Open privileged listing or dashboard — paginated table when applicable
2. Create or edit resource via form UX
3. Operational tables and privileged workspace views when in scope for the slice

Use dev auth tokens or the app's dev login flow as documented in `docs/technical/10-local-development-setup.md`.

## What the harness automates vs agent-driven

| Layer | Mechanism |
|---|---|
| Unit tests | `npm run test:unit` — validators, component tests |
| Integration tests | `npm run test:integration` — API + Postgres |
| API scenario tests | `npm run test:e2e` — in-process Fastify flows |
| HTTP stack probe | `verify-stack.sh` — health + web HTTP 200 |
| **Browser UI (implementer)** | Playwright MCP smoke test during implementation |
| **Browser UI (gate)** | `run-browser-test.sh` — dedicated test agent; `TC-*` checklist + UX audit + Playwright regression codegen |
| **Playwright UI regression** | `tests/playwright-ui/scenarios/` — committed specs; `npm run test:playwright-ui` (optional gate) |

### Post-verification (full phase)

After the `TC-*` checklist, the browser test agent:

1. **UX audit** — screenshot review per `skills/ui-ux-testing/SKILL.md`; logs `UX-<slice>-NNN` bugs (P0/P1 block pass)
2. **UX bugs JSON** — `ai-harness/generated/runs/ux-bugs/<slice-id>/<run-id>.json`
3. **Playwright codegen** — updates `tests/playwright-ui/scenarios/<slice-id>.spec.ts` per [`playwright-regression.md`](playwright-regression.md)

See [`ux-bug-logging.md`](ux-bug-logging.md) for bug schema and severity rules.

### Out-of-scope case results

Cases that require physical devices or are not applicable in Playwright MCP must be reported as `SKIP`, not `FAIL`:

- `TC-…: SKIP — physical-device — <reason>`
- `TC-…: SKIP — not-applicable — <reason>`

Skipped cases are excluded from pass/fail — `TC-*: FAIL` and `UX-*` P0/P1 lines block the gate.

Test case artifacts may declare `harnessSkip` on `layer: browser` cases (`physical-device` or `not-applicable`). The harness injects a **Harness scope: SKIP** line in the tester checklist for those cases.

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
