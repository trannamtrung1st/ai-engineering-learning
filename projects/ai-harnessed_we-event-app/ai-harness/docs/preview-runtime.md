# Preview Runtime — API + Web

Canonical harness spec for starting and verifying the We Event stack (database, API, web). Referenced by `ai-harness/README.md`, `ai-harness/HARNESS-DESIGN.md`, and `docs/technical/13-docker-compose-local-runtime.md`.

**Status:** Implemented. Scripts live in `ai-harness/scripts/`; root `package.json` npm scripts wired.

## Modes

| Mode | Flag | What starts | Use when |
|---|---|---|---|
| **Dev** (default) | `--mode dev` | Compose `db` + local `npm run dev` for API and web | Fast iteration with hot reload |
| **Full preview** | `--mode full` | Compose `db` + built API/web images (`full-preview` profile) | Production-like smoke validation |

## Startup success criteria

Both modes must pass the same verification probes before reporting success:

| Service | Probe | Success |
|---|---|---|
| API | `GET http://localhost:${AIH_PREVIEW_API_PORT:-3001}/api/v1/health` | JSON `status` is `ok` and `db` is `connected` |
| Web | `GET http://localhost:${AIH_PREVIEW_WEB_PORT:-3000}/` | HTTP status `200` |

Timeouts (defaults):

| Probe | Dev mode | Full preview |
|---|---|---|
| API health | 60s | 180s (first image build) |
| Web HTTP 200 | 120s | 180s |

Exit codes: `0` when all probes pass; `1` with stderr naming the failing service, last response, and timeout.

## Root npm script mapping

Wired in repository root `package.json`:

```json
"aih:preview": "./ai-harness/scripts/preview-stack.sh --mode dev",
"aih:preview:full": "./ai-harness/scripts/preview-stack.sh --mode full",
"aih:preview:down": "./ai-harness/scripts/preview-stack.sh --down",
"aih:preview:verify": "./ai-harness/scripts/verify-stack.sh"
```

## Script contract — `preview-stack.sh`

Location: `ai-harness/scripts/preview-stack.sh`

| Flag / env | Behavior |
|---|---|
| `--mode dev` | Default. `npm run aih:dev:db:up` → build API → start API + web dev processes in background → verify → print URLs and PIDs |
| `--mode full` | `docker compose --profile full-preview up -d --build` → verify → print URLs |
| `--verify-only` | Skip start; delegate to `verify-stack.sh` |
| `--down` | Dev: kill tracked PIDs + `npm run aih:dev:db:down`. Full: `docker compose --profile full-preview down` |
| `AIH_PREVIEW_API_PORT` | Default `3001` |
| `AIH_PREVIEW_WEB_PORT` | Default `3000` |
| `AIH_PREVIEW_MODE` | Optional override for `--mode` (`dev` \| `full`) |

State file (dev mode PIDs): `ai-harness/generated/runs/preview-stack.pids`

### Dev-mode prerequisites

1. Copy `.env.example` to `.env` (or export vars) — `DATABASE_URL` must target Compose Postgres (`localhost:5432`).
2. `npm run aih:dev:db:up` — database healthy before API start.
3. Run migrations against Postgres before API start.
4. `npm run build --workspace @we-event/api` — API `dev` script runs `node --watch dist/index.js`.
5. `preview-stack.sh` sets `PORT` per service when starting dev processes (`.env` defines `PORT=3001` for API; web must use `3000`).

### Full-mode prerequisites

- `docker-compose.yml` at repo root (present).
- `apps/api/Dockerfile` and `apps/web/Dockerfile` (backlog follow-up when absent).
- Docker available (`docker compose version`).

## Script contract — `verify-stack.sh`

Location: `ai-harness/scripts/verify-stack.sh`

Polls API health and web root until success or timeout. Used by:

- `preview-stack.sh` after start
- `npm run aih:preview:verify` (standalone / harness gate)
- Future `run-checks.sh` integration when `apps/api` and `apps/web` exist

Environment overrides:

| Variable | Default | Purpose |
|---|---|---|
| `AIH_PREVIEW_API_PORT` | `3001` | API host port |
| `AIH_PREVIEW_WEB_PORT` | `3000` | Web host port |
| `AIH_VERIFY_API_TIMEOUT_MS` | `60000` (dev) / `180000` (full) | API poll budget |
| `AIH_VERIFY_WEB_TIMEOUT_MS` | `120000` (dev) / `180000` (full) | Web poll budget |
| `AIH_PREVIEW_MODE` | `dev` | Selects default timeouts when explicit `*_TIMEOUT_MS` unset |

## Reference implementation — `verify-stack.sh`

Implemented at `ai-harness/scripts/verify-stack.sh`. Supports `--quick` (single attempt; skips when services are not listening).

```bash
#!/usr/bin/env bash
# Poll API health and web HTTP until startup succeeds or timeout.
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
require_cmd curl

API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
WEB_PORT="${AIH_PREVIEW_WEB_PORT:-3000}"
MODE="${AIH_PREVIEW_MODE:-dev}"

if [[ -z "${AIH_VERIFY_API_TIMEOUT_MS:-}" ]]; then
  [[ "$MODE" == "full" ]] && AIH_VERIFY_API_TIMEOUT_MS=180000 || AIH_VERIFY_API_TIMEOUT_MS=60000
fi
if [[ -z "${AIH_VERIFY_WEB_TIMEOUT_MS:-}" ]]; then
  [[ "$MODE" == "full" ]] && AIH_VERIFY_WEB_TIMEOUT_MS=180000 || AIH_VERIFY_WEB_TIMEOUT_MS=120000
fi

API_URL="http://localhost:${API_PORT}/api/v1/health"
WEB_URL="http://localhost:${WEB_PORT}/"

poll_api() {
  local deadline=$(( $(date +%s) * 1000 + AIH_VERIFY_API_TIMEOUT_MS ))
  local body status db
  while true; do
    if body="$(curl -sf "$API_URL" 2>/dev/null || true)"; then
      status="$(echo "$body" | jq -r '.status // empty' 2>/dev/null || true)"
      db="$(echo "$body" | jq -r '.db // empty' 2>/dev/null || true)"
      if [[ "$status" == "ok" && "$db" == "connected" ]]; then
        echo "API healthy: $API_URL"
        return 0
      fi
    else
      body="(no response)"
    fi
    if [[ $(date +%s) * 1000 -ge $deadline ]]; then
      echo "ERROR: API startup failed after ${AIH_VERIFY_API_TIMEOUT_MS}ms" >&2
      echo "  URL: $API_URL" >&2
      echo "  Last response: $body" >&2
      return 1
    fi
    sleep 2
  done
}

poll_web() {
  local deadline=$(( $(date +%s) * 1000 + AIH_VERIFY_WEB_TIMEOUT_MS ))
  local code
  while true; do
    code="$(curl -sf -o /dev/null -w '%{http_code}' "$WEB_URL" 2>/dev/null || echo "000")"
    if [[ "$code" == "200" ]]; then
      echo "Web ready: $WEB_URL (HTTP $code)"
      return 0
    fi
    if [[ $(date +%s) * 1000 -ge $deadline ]]; then
      echo "ERROR: Web startup failed after ${AIH_VERIFY_WEB_TIMEOUT_MS}ms" >&2
      echo "  URL: $WEB_URL" >&2
      echo "  Last HTTP status: $code" >&2
      return 1
    fi
    sleep 2
  done
}

cd "$REPO_ROOT"
poll_api
poll_web
echo "Stack startup verification passed (mode=$MODE)"
```

## Reference implementation — `preview-stack.sh`

Implemented at `ai-harness/scripts/preview-stack.sh`. Persists mode in `preview-stack.mode` for `--down`.

```bash
#!/usr/bin/env bash
# Start We Event stack (dev or full preview) and verify API + web startup.
# Usage: preview-stack.sh [--mode dev|full] [--verify-only] [--down]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERIFY_SCRIPT="${SCRIPT_DIR}/verify-stack.sh"
PID_FILE="${RUNS_DIR}/preview-stack.pids"
MODE="${AIH_PREVIEW_MODE:-dev}"
ACTION="up"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --mode=*) MODE="${1#*=}"; shift ;;
    --verify-only) ACTION="verify"; shift ;;
    --down) ACTION="down"; shift ;;
    -h|--help)
      echo "Usage: preview-stack.sh [--mode dev|full] [--verify-only] [--down]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

require_harness_deps
ensure_runs_dir
cd "$REPO_ROOT"

export AIH_PREVIEW_MODE="$MODE"

stop_dev_processes() {
  if [[ -f "$PID_FILE" ]]; then
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
}

case "$ACTION" in
  down)
    if [[ "$MODE" == "full" ]]; then
      docker compose --profile full-preview down
    else
      stop_dev_processes
      npm run aih:dev:db:down
    fi
    echo "Preview stack stopped (mode=$MODE)"
    exit 0
    ;;
  verify)
    exec "$VERIFY_SCRIPT"
    ;;
esac

if [[ "$MODE" == "full" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker required for full preview" >&2
    exit 1
  fi
  for df in apps/api/Dockerfile apps/web/Dockerfile; do
    if [[ ! -f "$REPO_ROOT/$df" ]]; then
      echo "ERROR: missing $df (required for full preview)" >&2
      exit 1
    fi
  done
  docker compose --profile full-preview up -d --build
else
  npm run aih:dev:db:up
  # Wait for db healthy
  for _ in $(seq 1 30); do
    status="$(docker compose ps --status running --format json db 2>/dev/null | jq -r '.Health // .State // empty' 2>/dev/null || true)"
    [[ "$status" == "healthy" || "$status" == "running" ]] && break
    sleep 2
  done
  npm run build --workspace @we-event/api
  stop_dev_processes
  : > "$PID_FILE"
  PORT="${AIH_PREVIEW_API_PORT:-3001}" npm run dev --workspace @we-event/api >>"${RUNS_DIR}/preview-api.log" 2>&1 &
  echo $! >> "$PID_FILE"
  PORT="${AIH_PREVIEW_WEB_PORT:-3000}" npm run dev --workspace @we-event/web >>"${RUNS_DIR}/preview-web.log" 2>&1 &
  echo $! >> "$PID_FILE"
fi

"$VERIFY_SCRIPT"

API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
WEB_PORT="${AIH_PREVIEW_WEB_PORT:-3000}"
echo ""
echo "Preview stack ready (mode=$MODE)"
echo "  API: http://localhost:${API_PORT}/api/v1/health"
echo "  Web: http://localhost:${WEB_PORT}/"
if [[ "$MODE" == "dev" && -f "$PID_FILE" ]]; then
  echo "  PIDs: $(tr '\n' ' ' < "$PID_FILE")"
  echo "  Logs: ${RUNS_DIR}/preview-api.log, ${RUNS_DIR}/preview-web.log"
fi
echo "  Stop: npm run aih:preview:down"
```

## Harness gate integration

`run-checks.sh` invokes `verify-stack.sh` and `verify-scenarios.sh` when `apps/api` and `apps/web` exist:

- **Default (`npm run aih:check`):** `--quick` — skips when services are not listening; fails if up but unhealthy.
- **Full poll:** set `AIH_VERIFY_STACK=1` before `aih:check` (expects preview stack running).
- **Slice-scoped web probe:** backend/infra slices use `verify-stack.sh --api-only` (API health only). Frontend and test slices also require web `GET /` HTTP 200.
- **Scenario probe:** `verify-scenarios.sh` runs independently of web health (API-only participant registration flow).
- **After build:** when preview is **not** running, full workspace build includes web. When preview **is** running, `run-checks.sh` skips `@we-event/web` build to avoid corrupting dev `.next` (typecheck still covers web).

### Dev-mode supervisors (auto-restart)

Dev preview starts two supervisor processes (`preview-supervisor.sh`) instead of bare `npm run dev`:

| Supervisor | Command | On crash |
|---|---|---|
| API | `node dist/index.js` (supervisor restarts; no `--watch`) | Restarts after 2s |
| Web | `next dev` | Restarts after 2s; honors refresh signal |

PID file (`preview-stack.pids`) stores **supervisor** PIDs (not child npm/next PIDs). Stop via `npm run aih:preview:down` sets `preview-supervisor.stop` and terminates supervisors cleanly.

Signal files in `ai-harness/generated/runs/`:

| File | Purpose |
|---|---|
| `preview-supervisor.stop` | Supervisors exit their restart loop |
| `preview-web.refresh` | Web supervisor clears `.next` before next start |

Override restart delay: `PREVIEW_RESTART_DELAY_SEC=5`

### Logging (all processes)

Every preview session writes timestamped, tagged logs under `ai-harness/generated/runs/`:

| File | Tag | Contents |
|---|---|---|
| `preview-combined.log` | all | Unified stream — best for debugging |
| `preview-stack.log` | `stack` | Start/stop, db up, build, verify |
| `preview-api.log` | `api`, `supervisor:api` | API dev + supervisor events |
| `preview-web.log` | `web`, `supervisor:web` | Web dev + supervisor events |
| `preview-db.log` | `db` | Postgres container (`docker compose logs -f db`) |

Full preview mode also tails all compose services into `preview-stack.log` with tag `compose`.

View logs:

```bash
# Last 50 lines of combined log (default)
npm run aih:preview:logs

# Follow all logs live
npm run aih:preview:logs -- --follow

# One service, more lines
npm run aih:preview:logs -- api --lines 200
npm run aih:preview:logs -- all --follow
```

Log lines format: `[2026-06-25T18:00:00Z][api] message`

### Web dev cache recovery

`next build` and `next dev` share `apps/web/.next`. While preview is up, harness checks skip web production build. If you run `next build` manually while preview is serving, restart preview:

Recovery:

```bash
npm run aih:preview:down
rm -rf apps/web/.next
npm run aih:preview
npm run aih:preview:verify
```

`aih:preview` clears `.next` before starting web dev.

## Quick reference

```bash
# Dev preview (DB in Docker, API + web local)
npm run aih:preview

# Full preview (all services in Docker)
npm run aih:preview:full

# Verify already-running stack (API + web)
npm run aih:preview:verify

# Participant registration API scenario (independent of web)
npm run aih:preview:scenarios

# View / follow logs (combined or per-service)
npm run aih:preview:logs
npm run aih:preview:logs -- --follow all

# Tear down
npm run aih:preview:down
```

Manual probes:

```bash
curl -sf http://localhost:3001/api/v1/health | jq .
curl -sf -o /dev/null -w '%{http_code}\n' http://localhost:3000/
```

## Related docs

- `docs/technical/13-docker-compose-local-runtime.md` — Compose services and ports
- `docs/technical/10-local-development-setup.md` — Local runbook
- `.env.example` — required environment variables
