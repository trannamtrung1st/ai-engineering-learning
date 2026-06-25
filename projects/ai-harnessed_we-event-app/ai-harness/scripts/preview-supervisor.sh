#!/usr/bin/env bash
# Supervise a preview dev process (api|web): restart on crash, honor stop/refresh signals.
# Usage: preview-supervisor.sh <api|web>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

SERVICE="${1:-}"
if [[ "$SERVICE" != "api" && "$SERVICE" != "web" ]]; then
  echo "Usage: preview-supervisor.sh <api|web>" >&2
  exit 1
fi

ensure_runs_dir
cd "$REPO_ROOT"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

log_supervisor() {
  preview_write_log "supervisor:${SERVICE}" "$log_file" "$*"
}

run_api() {
  PORT="${AIH_PREVIEW_API_PORT:-3001}" node "$REPO_ROOT/apps/api/dist/index.js"
}

run_web() {
  PORT="${AIH_PREVIEW_WEB_PORT:-3000}" npm run dev --workspace @we-event/web
}

maybe_refresh_web_cache() {
  [[ "$SERVICE" == "web" ]] || return 0
  [[ -f "$PREVIEW_WEB_REFRESH_FILE" ]] || return 0
  rm -f "$PREVIEW_WEB_REFRESH_FILE"
  log_supervisor "refresh requested — clearing apps/web/.next"
  remove_path_safely "$REPO_ROOT/apps/web/.next"
}

log_file="$PREVIEW_API_LOG"
run_cmd=run_api
process_tag="api"
if [[ "$SERVICE" == "web" ]]; then
  log_file="$PREVIEW_WEB_LOG"
  run_cmd=run_web
  process_tag="web"
fi

log_supervisor "supervisor started (pid=$$)"

while true; do
  if [[ -f "$PREVIEW_SUPERVISOR_STOP_FILE" ]]; then
    log_supervisor "stop signal received — exiting"
    exit 0
  fi

  maybe_refresh_web_cache

  log_supervisor "starting dev process"
  set +e
  $run_cmd 2>&1 | preview_tee_process_log "$process_tag" "$log_file"
  exit_code="${PIPESTATUS[0]}"
  set -e

  if [[ -f "$PREVIEW_SUPERVISOR_STOP_FILE" ]]; then
    log_supervisor "stop signal received after exit ($exit_code) — exiting"
    exit 0
  fi

  log_supervisor "dev process exited ($exit_code) — restarting in ${PREVIEW_RESTART_DELAY_SEC:-2}s"
  sleep "${PREVIEW_RESTART_DELAY_SEC:-2}"
done
