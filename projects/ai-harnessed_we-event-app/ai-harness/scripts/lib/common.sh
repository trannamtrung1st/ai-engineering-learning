#!/usr/bin/env bash
# Shared harness utilities
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$(cd "${HARNESS_ROOT}/.." && pwd)"

BACKLOG="${HARNESS_ROOT}/whole-app-backlog.json"
LOOP_CONFIG="${HARNESS_ROOT}/workflows/ralph-loop.json"
MODELS_CONFIG="${HARNESS_ROOT}/config/models.json"
CONTEXT_MAP="${HARNESS_ROOT}/config/context-map.json"
STATE_DIR="${HARNESS_ROOT}/state"
RUNS_DIR="${HARNESS_ROOT}/generated/runs"
PREVIEW_PID_FILE="${RUNS_DIR}/preview-stack.pids"
PREVIEW_AUX_PID_FILE="${RUNS_DIR}/preview-aux.pids"
PREVIEW_WEB_LOG="${RUNS_DIR}/preview-web.log"
PREVIEW_API_LOG="${RUNS_DIR}/preview-api.log"
PREVIEW_DB_LOG="${RUNS_DIR}/preview-db.log"
PREVIEW_STACK_LOG="${RUNS_DIR}/preview-stack.log"
PREVIEW_COMBINED_LOG="${RUNS_DIR}/preview-combined.log"
PREVIEW_SUPERVISOR_STOP_FILE="${RUNS_DIR}/preview-supervisor.stop"
PREVIEW_WEB_REFRESH_FILE="${RUNS_DIR}/preview-web.refresh"

export HARNESS_ROOT REPO_ROOT BACKLOG LOOP_CONFIG MODELS_CONFIG CONTEXT_MAP STATE_DIR RUNS_DIR
export PREVIEW_PID_FILE PREVIEW_AUX_PID_FILE
export PREVIEW_WEB_LOG PREVIEW_API_LOG PREVIEW_DB_LOG PREVIEW_STACK_LOG PREVIEW_COMBINED_LOG
export PREVIEW_SUPERVISOR_STOP_FILE PREVIEW_WEB_REFRESH_FILE

preview_log_files() {
  printf '%s\n' \
    "$PREVIEW_COMBINED_LOG" \
    "$PREVIEW_STACK_LOG" \
    "$PREVIEW_API_LOG" \
    "$PREVIEW_WEB_LOG" \
    "$PREVIEW_DB_LOG"
}

preview_log_ts() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

preview_write_log() {
  local tag="$1"
  local primary_log="${2:-}"
  local content="$3"
  local ts line
  ts="$(preview_log_ts)"
  line="[${ts}][${tag}] ${content}"
  ensure_runs_dir
  echo "$line" >> "$PREVIEW_COMBINED_LOG"
  if [[ -n "$primary_log" ]]; then
    echo "$line" >> "$primary_log"
  fi
}

preview_log_session_start() {
  local mode="${1:-dev}"
  local banner
  banner="======== preview session start mode=${mode} $(preview_log_ts) pid=$$ ========"
  ensure_runs_dir
  local log_file
  while IFS= read -r log_file; do
    echo "$banner" >> "$log_file"
  done < <(preview_log_files)
}

preview_log_stack() {
  preview_write_log "stack" "$PREVIEW_STACK_LOG" "$*"
}

preview_tee_process_log() {
  local tag="$1"
  local primary_log="$2"
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    preview_write_log "$tag" "$primary_log" "$line"
  done
}

stop_preview_log_followers() {
  if [[ ! -f "$PREVIEW_AUX_PID_FILE" ]]; then
    return 0
  fi
  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    terminate_pid "$pid"
  done < "$PREVIEW_AUX_PID_FILE"
  rm -f "$PREVIEW_AUX_PID_FILE"
}

start_preview_db_log_follower() {
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  ensure_runs_dir
  stop_preview_log_followers
  : > "$PREVIEW_AUX_PID_FILE"
  (
    docker compose logs -f --tail=50 db 2>&1 | preview_tee_process_log "db" "$PREVIEW_DB_LOG"
  ) &
  echo $! >> "$PREVIEW_AUX_PID_FILE"
  preview_log_stack "db log follower started (pid=$!)"
}

start_preview_compose_log_follower() {
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  ensure_runs_dir
  stop_preview_log_followers
  : > "$PREVIEW_AUX_PID_FILE"
  (
    docker compose --profile full-preview logs -f --tail=100 2>&1 | preview_tee_process_log "compose" "$PREVIEW_STACK_LOG"
  ) &
  echo $! >> "$PREVIEW_AUX_PID_FILE"
  preview_log_stack "compose log follower started (pid=$!)"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_harness_deps() {
  require_cmd jq
}

# Search files for pattern. Uses rg when installed, otherwise grep -r.
search_files() {
  local pattern="$1"
  shift
  local paths=("$@")
  [[ ${#paths[@]} -eq 0 ]] && return 0
  if command -v rg >/dev/null 2>&1; then
    rg -i -l "$pattern" "${paths[@]}" 2>/dev/null || true
  else
    grep -Ri -l -E "$pattern" "${paths[@]}" 2>/dev/null || true
  fi
}

file_contains() {
  local pattern="$1"
  local file="$2"
  if command -v rg >/dev/null 2>&1; then
    rg -q "$pattern" "$file" 2>/dev/null
  else
    grep -qE "$pattern" "$file" 2>/dev/null
  fi
}

require_agent() {
  AGENT_BIN="$(resolve_agent_bin)"
  if [[ -z "$AGENT_BIN" ]]; then
    echo "ERROR: Cursor CLI not found. Install: curl https://cursor.com/install -fsS | bash" >&2
    echo "Then authenticate: agent login" >&2
    exit 1
  fi
  export AGENT_BIN
}

get_model() {
  local key="${1:-default}"
  if [[ -n "${AIH_MODEL:-}" ]]; then
    echo "$AIH_MODEL"
    return
  fi
  if [[ "$key" == "reviewer" && -n "${AIH_REVIEWER_MODEL:-}" ]]; then
    echo "$AIH_REVIEWER_MODEL"
    return
  fi
  jq -r --arg k "$key" '.[$k] // .default' "$MODELS_CONFIG"
}

resolve_agent_bin() {
  if command -v agent >/dev/null 2>&1; then
    echo "agent"
  elif command -v cursor-agent >/dev/null 2>&1; then
    echo "cursor-agent"
  else
    echo ""
  fi
}

print_harness_env() {
  local bin
  bin="$(resolve_agent_bin)"
  if [[ -n "$bin" ]]; then
    echo "Agent: ${bin} | Model: $(get_model default) | Reviewer: $(get_model reviewer)"
  else
    echo "Agent: not installed (curl https://cursor.com/install -fsS | bash)"
  fi
  echo "Auth: agent login (OAuth, one-time per machine)"
  echo "Overrides: AIH_MODEL=... AIH_SKIP_AGENT=1 AIH_SKIP_REVIEW=1"
}

run_id() {
  date -u +"%Y%m%dT%H%M%SZ"
}

ensure_runs_dir() {
  mkdir -p "$RUNS_DIR"
}

all_slices_pass() {
  local pending
  pending="$(jq '[.slices[] | select(.passes == false)] | length' "$BACKLOG")"
  [[ "$pending" -eq 0 ]]
}

pick_next_slice_id() {
  jq -r '
    [.slices[] | select(.passes == false)]
    | sort_by(.priority)
    | .[0].id // empty
  ' "$BACKLOG"
}

get_slice_field() {
  local slice_id="$1"
  local field="$2"
  jq -r --arg id "$slice_id" --arg f "$field" '
    .slices[] | select(.id == $id) | .[$f]
  ' "$BACKLOG"
}

get_slice_json() {
  local slice_id="$1"
  jq -c --arg id "$slice_id" '.slices[] | select(.id == $id)' "$BACKLOG"
}

mark_slice_passed() {
  local slice_id="$1"
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$slice_id" '
    .slices |= map(if .id == $id then .passes = true else . end)
  ' "$BACKLOG" > "$tmp" && mv "$tmp" "$BACKLOG"
}

append_guardrail() {
  local slice_id="$1"
  local message="$2"
  echo "- [${slice_id}] ${message}" >> "${STATE_DIR}/guardrails.md"
}

append_progress() {
  local slice_id="$1"
  local status="$2"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "- ${ts} | ${slice_id} | ${status}" >> "${STATE_DIR}/progress.md"
}

write_run_report() {
  local name="$1"
  local content="$2"
  ensure_runs_dir
  echo "$content" > "${RUNS_DIR}/${name}"
}

agent_invoke() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  local slice_id="${4:-${AIH_CHECK_SLICE:-}}"
  require_agent
  local -a args=(-p --force --output-format text --model "$model")
  if slice_requires_web_runtime "$slice_id" || [[ "${AIH_BROWSER_MCP:-}" == "1" ]]; then
    args+=(--approve-mcps)
  fi
  if [[ -n "$outfile" ]]; then
    "$AGENT_BIN" "${args[@]}" "$prompt" | tee "$outfile"
    return "${PIPESTATUS[0]}"
  fi
  "$AGENT_BIN" "${args[@]}" "$prompt"
}

# Read-only reviewer: plan mode blocks edits; prompt forbids shell/tests.
agent_invoke_review() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args=(-p --force --trust --output-format text --model "$model" --mode plan)
  if [[ -n "$outfile" ]]; then
    "$AGENT_BIN" "${args[@]}" "$prompt" | tee "$outfile"
    return "${PIPESTATUS[0]}"
  fi
  "$AGENT_BIN" "${args[@]}" "$prompt"
}

git_changed_files() {
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    return 0
  fi
  {
    git diff --name-only HEAD 2>/dev/null || true
    git diff --cached --name-only 2>/dev/null || true
    git ls-files --others --exclude-standard 2>/dev/null || true
  } | sed '/^$/d' | sort -u
}

find_checks_report_for_slice() {
  local slice_id="$1"
  local run_id="${2:-}"
  if [[ -n "$run_id" && -f "${RUNS_DIR}/${run_id}-checks.json" ]]; then
    cat "${RUNS_DIR}/${run_id}-checks.json"
    return 0
  fi
  local f
  for f in $(ls -t "${RUNS_DIR}"/*-checks.json 2>/dev/null || true); do
    if jq -e --arg s "$slice_id" '.slice == $s and .pass == true' "$f" >/dev/null 2>&1; then
      cat "$f"
      return 0
    fi
  done
  echo '{"pass":false,"note":"no checks report found for slice"}'
}

# Backend/infra slices only require API runtime probes; frontend/test need web too.
slice_requires_web_runtime() {
  local slice_id="${1:-}"
  if [[ -z "$slice_id" ]]; then
    return 0
  fi
  local agent
  agent="$(get_slice_field "$slice_id" agent)"
  [[ "$agent" == "frontend" || "$agent" == "test" ]]
}

terminate_pid() {
  local pid="$1"
  [[ -z "$pid" ]] && return 0
  kill "$pid" 2>/dev/null || true
  pkill -P "$pid" 2>/dev/null || true
  local _
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.3
  done
  kill -9 "$pid" 2>/dev/null || true
  pkill -9 -P "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

preview_supervisor_script() {
  echo "${HARNESS_ROOT}/scripts/preview-supervisor.sh"
}

preview_stack_is_running() {
  [[ -f "$PREVIEW_PID_FILE" ]] || return 1
  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    kill -0 "$pid" 2>/dev/null && return 0
  done < "$PREVIEW_PID_FILE"
  return 1
}

read_preview_supervisor_pids() {
  PREVIEW_API_SUPERVISOR_PID=""
  PREVIEW_WEB_SUPERVISOR_PID=""
  [[ -f "$PREVIEW_PID_FILE" ]] || return 1
  local -a pids=()
  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    pids+=("$pid")
  done < "$PREVIEW_PID_FILE"
  [[ ${#pids[@]} -ge 1 ]] && PREVIEW_API_SUPERVISOR_PID="${pids[0]}"
  [[ ${#pids[@]} -ge 2 ]] && PREVIEW_WEB_SUPERVISOR_PID="${pids[1]}"
  export PREVIEW_API_SUPERVISOR_PID PREVIEW_WEB_SUPERVISOR_PID
}

stop_preview_supervisors() {
  ensure_runs_dir
  preview_log_stack "stopping preview supervisors"
  touch "$PREVIEW_SUPERVISOR_STOP_FILE"
  rm -f "$PREVIEW_WEB_REFRESH_FILE"

  if [[ -f "$PREVIEW_PID_FILE" ]]; then
    local pid
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      terminate_pid "$pid"
    done < "$PREVIEW_PID_FILE"
    rm -f "$PREVIEW_PID_FILE"
  fi

  stop_preview_log_followers
  sleep 0.5
  rm -f "$PREVIEW_SUPERVISOR_STOP_FILE"
  preview_log_stack "preview supervisors stopped"
}

start_preview_supervisors() {
  local supervisor_script
  supervisor_script="$(preview_supervisor_script)"
  ensure_runs_dir
  rm -f "$PREVIEW_SUPERVISOR_STOP_FILE" "$PREVIEW_WEB_REFRESH_FILE"
  : > "$PREVIEW_PID_FILE"

  "$supervisor_script" api &
  echo $! >> "$PREVIEW_PID_FILE"
  local api_sup=$!
  "$supervisor_script" web &
  echo $! >> "$PREVIEW_PID_FILE"
  local web_sup=$!
  preview_log_stack "supervisors started (api=${api_sup}, web=${web_sup})"
}

# Kill the dev child on a port so its supervisor restarts it.
nudge_preview_service_restart() {
  local port="$1"
  local self_pid="${2:-}"

  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi

  local port_pid
  while IFS= read -r port_pid; do
    [[ -z "$port_pid" ]] && continue
    [[ -n "$self_pid" && "$port_pid" == "$self_pid" ]] && continue
    [[ -n "${PREVIEW_WEB_SUPERVISOR_PID:-}" && "$port_pid" == "$PREVIEW_WEB_SUPERVISOR_PID" ]] && continue
    [[ -n "${PREVIEW_API_SUPERVISOR_PID:-}" && "$port_pid" == "$PREVIEW_API_SUPERVISOR_PID" ]] && continue
    terminate_pid "$port_pid"
  done < <(lsof -ti ":${port}" 2>/dev/null || true)
}

nudge_preview_api_restart() {
  read_preview_supervisor_pids || return 0
  nudge_preview_service_restart "${AIH_PREVIEW_API_PORT:-3001}"
}

nudge_preview_web_restart() {
  read_preview_supervisor_pids || return 0
  touch "$PREVIEW_WEB_REFRESH_FILE"
  nudge_preview_service_restart "${AIH_PREVIEW_WEB_PORT:-3000}"
}

remove_path_safely() {
  local target="$1"
  [[ -e "$target" ]] || return 0
  chmod -R u+w "$target" 2>/dev/null || true
  if rm -rf "$target" 2>/dev/null; then
    return 0
  fi
  local _
  for _ in 1 2 3 4 5; do
    sleep 0.5
    chmod -R u+w "$target" 2>/dev/null || true
    rm -rf "$target" 2>/dev/null && return 0
  done
  echo "WARN: could not remove ${target} (locked or permission denied); continuing" >&2
  return 0
}

stop_preview_web_process() {
  nudge_preview_web_restart
  sleep 0.5
}

clean_web_next_cache() {
  [[ -d "$REPO_ROOT/apps/web" ]] || return 0
  if preview_stack_is_running; then
    nudge_preview_web_restart
  fi
  remove_path_safely "$REPO_ROOT/apps/web/.next"
}

print_preview_web_hint() {
  echo "  Hint: next build + next dev can corrupt apps/web/.next. Recovery:" >&2
  echo "    npm run aih:preview:down && rm -rf apps/web/.next && npm run aih:preview" >&2
  echo "  Logs: npm run aih:preview:logs -- web" >&2
  if [[ -f "$PREVIEW_WEB_LOG" ]]; then
    echo "  Last lines of ${PREVIEW_WEB_LOG}:" >&2
    tail -n 8 "$PREVIEW_WEB_LOG" >&2 || true
  fi
}

# No-op when preview is up: run_build_for_checks skips web build to avoid .next corruption.
refresh_preview_web_after_build() {
  [[ -d "$REPO_ROOT/apps/web" ]] || return 0
  if preview_stack_is_running; then
    return 0
  fi
}

# Build all workspaces except web while preview dev is serving (avoids .next corruption).
run_build_for_checks() {
  local ws
  local pkg
  local -a workspaces=(
    "@we-event/api:apps/api"
    "@we-event/domain:packages/domain"
    "@we-event/config:packages/config"
    "@we-event/web:apps/web"
  )

  if preview_stack_is_running; then
    echo "Preview stack running — skipping @we-event/web build to preserve dev .next cache"
    for ws in "${workspaces[@]}"; do
      [[ "${ws##*:}" == "apps/web" ]] && continue
      pkg="${ws%%:*}"
      if [[ -f "$REPO_ROOT/${ws##*:}/package.json" ]] && jq -e --arg s "build" '.scripts[$s] // empty' "$REPO_ROOT/${ws##*:}/package.json" >/dev/null 2>&1; then
        npm run build --workspace "$pkg" || return 1
        if [[ "$pkg" == "@we-event/api" ]]; then
          nudge_preview_api_restart
        fi
      fi
    done
    return 0
  fi

  npm run build || return 1
}
