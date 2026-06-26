# Browser MCP — Playwright functional testing

Interactive UI verification for frontend and test slices. The harness enables Playwright MCP for implementer agents on `frontend` and `test` slices (`--approve-mcps`).

## Prerequisites

| Step | Command |
|---|---|
| Install Chromium (one-time) | `npx playwright install chromium` |
| Approve MCP for headless loop | `agent mcp enable playwright` |
| Start preview stack | `npm run aih:preview` |
| Verify stack | `npm run aih:preview:verify` |

Project MCP config: [`.cursor/mcp.json`](../../.cursor/mcp.json) — writes snapshots to `ai-harness/generated/runs/playwright-mcp` (gitignored). Add `--headless` to args for unattended background loops; omit it for local visual debugging.

## Artifact cleanup

Playwright MCP writes timestamped page snapshots (`.yml`) and console logs. The harness cleans these automatically before each implementer run on `frontend`/`test` slices (or when `AIH_BROWSER_MCP=1`).

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
| **Browser UI** | **Playwright MCP** — agent-driven; not a computational gate |

API-level e2e remains the automated acceptance gate. Playwright MCP supplements with real rendered UI verification.

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
| Stale Next cache | `npm run aih:preview:down && rm -rf apps/web/.next && npm run aih:preview` |
| Force MCP on any slice | `AIH_BROWSER_MCP=1 npm run aih:once` |

## Related docs

- [`preview-runtime.md`](preview-runtime.md) — preview stack and HTTP probes
- [`../README.md`](../README.md) — harness commands and env vars
- `docs/technical/11-testing-plan.md` — test pyramid and acceptance matrix
