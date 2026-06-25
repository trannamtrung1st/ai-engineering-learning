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
PREVIEW_WEB_LOG="${RUNS_DIR}/preview-web.log"
PREVIEW_API_LOG="${RUNS_DIR}/preview-api.log"

export HARNESS_ROOT REPO_ROOT BACKLOG LOOP_CONFIG MODELS_CONFIG CONTEXT_MAP STATE_DIR RUNS_DIR
export PREVIEW_PID_FILE PREVIEW_WEB_LOG PREVIEW_API_LOG

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
  require_agent
  local -a args=(-p --force --output-format text --model "$model")
  if [[ -n "$outfile" ]]; then
    "$AGENT_BIN" "${args[@]}" "$prompt" | tee "$outfile"
    return "${PIPESTATUS[0]}"
  fi
  "$AGENT_BIN" "${args[@]}" "$prompt"
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
  local web_port="${AIH_PREVIEW_WEB_PORT:-3000}"
  local web_pid=""

  if [[ -f "$PREVIEW_PID_FILE" ]]; then
    local -a pids=()
    local pid
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      pids+=("$pid")
    done < "$PREVIEW_PID_FILE"
    if [[ ${#pids[@]} -ge 2 ]]; then
      web_pid="${pids[1]}"
      terminate_pid "$web_pid"
    fi
  fi

  if command -v lsof >/dev/null 2>&1; then
    local port_pid
    while IFS= read -r port_pid; do
      [[ -z "$port_pid" ]] && continue
      [[ -n "$web_pid" && "$port_pid" == "$web_pid" ]] && continue
      terminate_pid "$port_pid"
    done < <(lsof -ti ":${web_port}" 2>/dev/null || true)
  fi

  sleep 0.5
}

clean_web_next_cache() {
  [[ -d "$REPO_ROOT/apps/web" ]] || return 0
  stop_preview_web_process
  remove_path_safely "$REPO_ROOT/apps/web/.next"
}

print_preview_web_hint() {
  echo "  Hint: next build + next dev can corrupt apps/web/.next. Recovery:" >&2
  echo "    npm run aih:preview:down && rm -rf apps/web/.next && npm run aih:preview" >&2
  if [[ -f "$PREVIEW_WEB_LOG" ]]; then
    echo "  Last lines of ${PREVIEW_WEB_LOG}:" >&2
    tail -n 8 "$PREVIEW_WEB_LOG" >&2 || true
  fi
}

# After root build, restart preview web dev so it does not serve stale .next chunks.
refresh_preview_web_after_build() {
  [[ -d "$REPO_ROOT/apps/web" ]] || return 0
  [[ -f "$PREVIEW_PID_FILE" ]] || return 0

  local -a pids=()
  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    pids+=("$pid")
  done < "$PREVIEW_PID_FILE"

  [[ ${#pids[@]} -ge 2 ]] || return 0
  local web_pid="${pids[1]}"
  kill -0 "$web_pid" 2>/dev/null || return 0

  stop_preview_web_process
  remove_path_safely "$REPO_ROOT/apps/web/.next"
  ensure_runs_dir
  if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
  fi
  PORT="${AIH_PREVIEW_WEB_PORT:-3000}" npm run dev --workspace @we-event/web >>"$PREVIEW_WEB_LOG" 2>&1 &
  local new_pid=$!
  {
    echo "${pids[0]}"
    echo "$new_pid"
  } > "$PREVIEW_PID_FILE"
  sleep 2
  echo "Refreshed preview web dev (pid=${new_pid}) after build"
}
