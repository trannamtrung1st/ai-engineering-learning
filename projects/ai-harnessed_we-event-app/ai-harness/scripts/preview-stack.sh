#!/usr/bin/env bash
# Start We Event stack (dev or full preview) and verify API + web startup.
# Usage: preview-stack.sh [--mode dev|full] [--verify-only] [--down]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERIFY_SCRIPT="${SCRIPT_DIR}/verify-stack.sh"
PID_FILE="${PREVIEW_PID_FILE}"
MODE_FILE="${RUNS_DIR}/preview-stack.mode"
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

load_preview_env() {
  if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
    return
  fi
  echo "WARN: no .env at repo root — copy .env.example and adjust DATABASE_URL" >&2
}

stop_dev_processes() {
  if [[ -f "$PID_FILE" ]]; then
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      terminate_pid "$pid"
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  sleep 0.5
}

wait_db_healthy() {
  local status
  for _ in $(seq 1 30); do
    status="$(docker compose ps --status running --format json db 2>/dev/null | jq -r '.Health // .State // empty' 2>/dev/null || true)"
    if [[ "$status" == "healthy" || "$status" == "running" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "ERROR: db service not healthy after wait" >&2
  return 1
}

case "$ACTION" in
  down)
    if [[ -f "$MODE_FILE" ]]; then
      MODE="$(cat "$MODE_FILE")"
      export AIH_PREVIEW_MODE="$MODE"
    fi
    if [[ "$MODE" == "full" ]]; then
      docker compose --profile full-preview down
    else
      stop_dev_processes
      npm run aih:dev:db:down
    fi
    rm -f "$MODE_FILE"
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
  wait_db_healthy
  load_preview_env
  npm run build --workspace @we-event/api
  stop_dev_processes
  clean_web_next_cache
  : > "$PID_FILE"
  PORT="${AIH_PREVIEW_API_PORT:-3001}" npm run dev --workspace @we-event/api >>"${PREVIEW_API_LOG}" 2>&1 &
  echo $! >> "$PID_FILE"
  PORT="${AIH_PREVIEW_WEB_PORT:-3000}" npm run dev --workspace @we-event/web >>"${PREVIEW_WEB_LOG}" 2>&1 &
  echo $! >> "$PID_FILE"
fi

echo "$MODE" > "$MODE_FILE"
"$VERIFY_SCRIPT"

API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
WEB_PORT="${AIH_PREVIEW_WEB_PORT:-3000}"
echo ""
echo "Preview stack ready (mode=$MODE)"
echo "  API: http://localhost:${API_PORT}/api/v1/health"
echo "  Web: http://localhost:${WEB_PORT}/"
if [[ "$MODE" == "dev" && -f "$PID_FILE" ]]; then
  echo "  PIDs: $(tr '\n' ' ' < "$PID_FILE")"
  echo "  Logs: ${PREVIEW_API_LOG}, ${PREVIEW_WEB_LOG}"
fi
echo "  Stop: npm run aih:preview:down"
