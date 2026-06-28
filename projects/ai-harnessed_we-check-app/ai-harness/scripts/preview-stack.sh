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
    # Preview always seeds browser fixtures; do not inherit SEED_ENABLED=false from local .env.
    export SEED_ENABLED=true
    return
  fi
  echo "WARN: no .env at repo root — copy .env.example and adjust DATABASE_URL" >&2
  export SEED_ENABLED=true
}

stop_dev_processes() {
  stop_dev_preview_processes
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
      preview_log_stack "stopping full preview compose stack"
      stop_preview_log_followers
      docker compose --profile full-preview down
    else
      preview_log_stack "stopping dev preview stack"
      stop_dev_processes
      preview_log_stack "bringing down database"
      npm run aih:dev:db:down 2>&1 | preview_tee_process_log "stack" "$PREVIEW_STACK_LOG" || true
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
  preview_log_session_start "full"
  preview_log_stack "starting full preview compose stack"
  set +e
  docker compose --profile full-preview up -d --build 2>&1 | preview_tee_process_log "stack" "$PREVIEW_STACK_LOG"
  compose_status=${PIPESTATUS[0]}
  set -e
  if [[ "$compose_status" -ne 0 ]]; then
    preview_log_stack "compose up failed (exit $compose_status)"
    exit "$compose_status"
  fi
  start_preview_compose_log_follower
else
  load_preview_env
  reset_dev_preview_stack
  preview_log_session_start "$MODE"
  preview_log_stack "starting dev preview stack"
  preview_log_stack "bringing up database"
  npm run aih:dev:db:up 2>&1 | preview_tee_process_log "stack" "$PREVIEW_STACK_LOG" || true
  preview_log_stack "waiting for database health"
  wait_db_healthy
  preview_log_stack "building API workspace"
  set +e
  npm run build --workspace @wecheck/api 2>&1 | preview_tee_process_log "stack" "$PREVIEW_STACK_LOG"
  build_status=${PIPESTATUS[0]}
  set -e
  if [[ "$build_status" -ne 0 ]]; then
    preview_log_stack "API build failed (exit $build_status)"
    exit "$build_status"
  fi
  start_preview_supervisors
  start_preview_db_log_follower
fi

echo "$MODE" > "$MODE_FILE"
preview_log_stack "running startup verification"
set +e
"$VERIFY_SCRIPT" 2>&1 | preview_tee_process_log "stack" "$PREVIEW_STACK_LOG"
verify_status=${PIPESTATUS[0]}
set -e
if [[ "$verify_status" -ne 0 ]]; then
  preview_log_stack "startup verification failed (exit $verify_status)"
  exit "$verify_status"
fi
preview_log_stack "startup verification passed"

API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
WEB_PORT="${AIH_PREVIEW_WEB_PORT:-3000}"
aih_blank
aih_section "Preview stack ready (mode=${MODE})" loop
aih_kv "API" "http://localhost:${API_PORT}/api/v1/health"
aih_kv "Web" "http://localhost:${WEB_PORT}/"
if [[ -f "$PID_FILE" || -f "$PREVIEW_AUX_PID_FILE" || "$MODE" == "full" ]]; then
  aih_kv "Logs" "npm run aih:preview:logs -- --follow"
  aih_info "combined: ${PREVIEW_COMBINED_LOG}"
  aih_info "stack:    ${PREVIEW_STACK_LOG}"
  if [[ "$MODE" == "dev" && -f "$PID_FILE" ]]; then
    aih_info "supervisors: $(tr '\n' ' ' < "$PID_FILE") (auto-restart on crash)"
    aih_info "api: ${PREVIEW_API_LOG}"
    aih_info "web: ${PREVIEW_WEB_LOG}"
    aih_info "db:  ${PREVIEW_DB_LOG}"
  fi
fi
aih_kv "Stop" "npm run aih:preview:down"
