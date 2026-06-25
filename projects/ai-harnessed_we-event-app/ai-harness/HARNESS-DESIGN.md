# AI Harness Design — We Event

Concise index for the 12 harness components. Referenced by `docs/technical/13-docker-compose-local-runtime.md`.

## Component map

| Component | Location |
|---|---|
| Model | `config/models.json`, env `AIH_MODEL` |
| Prompt | `agents/implementer.prompt.md`, `agents/reviewer.prompt.md` |
| Context | `config/context-map.json` — doc pointers per slice/agent |
| Tools | Cursor CLI (`agent -p --force`) + Playwright MCP on frontend/test slices |
| Workflow | `workflows/ralph-loop.json` |
| Memory/State | `state/progress.md`, `state/guardrails.md`, `whole-app-backlog.json` (in `ai-harness/`) |
| Validation | `scripts/run-checks.sh` — layered `test:unit`, `test:integration`, `test:e2e`, `testRequirements` |
| Guardrails | `state/guardrails.md` + forbidden patterns in `ralph-loop.json` |
| Observability | `generated/runs/<timestamp>-*.json` |
| Feedback loops | Failed check/review → guardrails append → retry |
| Human review | `workflows/human-review-checklist.md` |
| Preview runtime | `scripts/preview-stack.sh`, `docs/preview-runtime.md` |
| Browser MCP | `.cursor/mcp.json`, `docs/browser-mcp.md` |
| Startup verification | `scripts/verify-stack.sh` |
| Runtime | `ralph-loop.json` → `runtimeValidation` (db, api, web) |

## Ralph loop

Each iteration spawns a **fresh** agent context (no `--resume`). State lives on disk and in git.

```
pick slice → build prompt → agent implement → run-checks → run-ai-review → mark pass → commit
```

Scripts: `ralph-loop.sh` (autonomous), `ralph-once.sh` (single step).

## Backlog

`ai-harness/whole-app-backlog.json` — phased slices with `passes`, `priority`, `acceptance`, `completionArtifacts`.

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
