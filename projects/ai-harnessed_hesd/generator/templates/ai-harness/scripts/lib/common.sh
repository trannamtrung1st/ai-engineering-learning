#!/usr/bin/env bash
# Shared harness utilities
set -euo pipefail

# shellcheck source=console.sh
source "$(dirname "${BASH_SOURCE[0]}")/console.sh"

HARNESS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$(cd "${HARNESS_ROOT}/.." && pwd)"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

aih_web_port() {
  echo "${AIH_PREVIEW_WEB_PORT:-${WEB_PORT:-3007}}"
}

aih_api_port() {
  echo "${AIH_PREVIEW_API_PORT:-${API_PORT:-3001}}"
}

BACKLOG="${HARNESS_ROOT}/whole-app-backlog.json"
TEST_CASE_INDEX="${HARNESS_ROOT}/test-case-index.json"
TESTGEN_DOCS_MAP="${HARNESS_ROOT}/config/testgen-docs-map.json"
LOOP_CONFIG="${HARNESS_ROOT}/workflows/ralph-loop.json"
TESTGEN_CONFIG="${HARNESS_ROOT}/workflows/testgen-loop.json"
MODELS_CONFIG="${HARNESS_ROOT}/config/models.json"
CONTEXT_MAP="${HARNESS_ROOT}/config/context-map.json"
STATE_DIR="${HARNESS_ROOT}/state"
LOOP_STATE="${STATE_DIR}/loop-state.json"
RUNS_DIR="${HARNESS_ROOT}/generated/runs"
SCREENSHOTS_ROOT="${RUNS_DIR}/screenshots"
TEST_CASES_DIR="${REPO_ROOT}/docs/test-cases"
PREVIEW_PID_FILE="${RUNS_DIR}/preview-stack.pids"
PREVIEW_AUX_PID_FILE="${RUNS_DIR}/preview-aux.pids"
PREVIEW_WEB_LOG="${RUNS_DIR}/preview-web.log"
PREVIEW_API_LOG="${RUNS_DIR}/preview-api.log"
PREVIEW_DB_LOG="${RUNS_DIR}/preview-db.log"
PREVIEW_STACK_LOG="${RUNS_DIR}/preview-stack.log"
PREVIEW_COMBINED_LOG="${RUNS_DIR}/preview-combined.log"
PREVIEW_SUPERVISOR_STOP_FILE="${RUNS_DIR}/preview-supervisor.stop"
PREVIEW_WEB_REFRESH_FILE="${RUNS_DIR}/preview-web.refresh"
PLAYWRIGHT_MCP_LEGACY_DIR="${REPO_ROOT}/.playwright-mcp"
PLAYWRIGHT_MCP_OUTPUT_DIR="${RUNS_DIR}/playwright-mcp"
PLAYWRIGHT_REGRESSION_INDEX="${HARNESS_ROOT}/playwright-regression-index.json"
UX_BUGS_ROOT="${RUNS_DIR}/ux-bugs"
PLAYWRIGHT_UI_SCENARIOS_DIR="${REPO_ROOT}/tests/playwright-ui/scenarios"

export HARNESS_ROOT REPO_ROOT BACKLOG TEST_CASE_INDEX TESTGEN_DOCS_MAP LOOP_CONFIG TESTGEN_CONFIG MODELS_CONFIG CONTEXT_MAP STATE_DIR RUNS_DIR SCREENSHOTS_ROOT TEST_CASES_DIR
export PREVIEW_PID_FILE PREVIEW_AUX_PID_FILE
export PREVIEW_WEB_LOG PREVIEW_API_LOG PREVIEW_DB_LOG PREVIEW_STACK_LOG PREVIEW_COMBINED_LOG
export PREVIEW_SUPERVISOR_STOP_FILE PREVIEW_WEB_REFRESH_FILE
export PLAYWRIGHT_MCP_LEGACY_DIR PLAYWRIGHT_MCP_OUTPUT_DIR

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

preview_clear_logs() {
  ensure_runs_dir
  local log_file
  while IFS= read -r log_file; do
    : > "$log_file"
  done < <(preview_log_files)
}

preview_log_session_start() {
  local mode="${1:-dev}"
  # Stop stale followers/supervisors before truncate so they cannot repopulate old lines.
  stop_preview_log_followers
  if [[ "$mode" != "full" ]]; then
    stop_preview_supervisors
    stop_stray_preview_supervisors
    stop_preview_port_listeners
    wait_for_preview_ports_free
  fi
  preview_clear_logs
  local banner
  banner="======== preview session start mode=${mode} $(preview_log_ts) pid=$$ ========"
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
  ) </dev/null >/dev/null 2>&1 &
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
  ) </dev/null >/dev/null 2>&1 &
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
  if [[ "$key" == "default" && -n "${AIH_MODEL:-}" ]]; then
    echo "$AIH_MODEL"
    return
  fi
  if [[ "$key" == "reviewer" && -n "${AIH_REVIEWER_MODEL:-}" ]]; then
    echo "$AIH_REVIEWER_MODEL"
    return
  fi
  if [[ "$key" == "tester" && -n "${AIH_TESTER_MODEL:-}" ]]; then
    echo "$AIH_TESTER_MODEL"
    return
  fi
  if [[ "$key" == "testgen" && -n "${AIH_TESTGEN_MODEL:-}" ]]; then
    echo "$AIH_TESTGEN_MODEL"
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
  echo "$(aih_bold "$(aih_cyan "Harness")")"
  if [[ -n "$bin" ]]; then
    aih_kv "Agent" "$bin"
    aih_kv "Model" "$(get_model default)"
    aih_kv "Reviewer" "$(get_model reviewer)"
    aih_kv "Tester" "$(get_model tester)"
    aih_kv "TestGen" "$(get_model testgen)"
  else
    aih_kv "Agent" "not installed (curl https://cursor.com/install -fsS | bash)"
  fi
  aih_kv "Auth" "agent login (OAuth, one-time per machine)"
  aih_kv "Timeout" "idle $(get_agent_idle_timeout_ms)ms / max $(get_agent_timeout_ms)ms (AIH_AGENT_IDLE_TIMEOUT_MS / AIH_AGENT_TIMEOUT_MS)"
  aih_kv "Overrides" "AIH_MODEL=... AIH_SKIP_AGENT=1 AIH_SKIP_REVIEW=1"
}

AGENT_TIMEOUT_EXIT=124
AGENT_TIMEOUT_DEFAULT_MS=3600000
AGENT_IDLE_TIMEOUT_DEFAULT_MS=300000
AGENT_SIGNAL_GRACE_DEFAULT_MS=15000
AGENT_RESULT_GRACE_DEFAULT_MS=5000
PREVIEW_VERIFY_GATE_DEFAULT_MS=10000
CHECK_COMMAND_TIMEOUT_DEFAULT_MS=600000
CHECK_COMMAND_TIMEOUT_POLL_MS=1000
CHECK_HEARTBEAT_DEFAULT_MS=30000

get_check_heartbeat_ms() {
  echo "${AIH_CHECK_HEARTBEAT_MS:-$CHECK_HEARTBEAT_DEFAULT_MS}"
}

# Path for per-script computational check log (gitignored under generated/runs).
check_log_path_for_script() {
  local script="$1"
  local rid="${RID:-$(run_id)}"
  local safe="${script//[:]/-}"
  echo "${RUNS_DIR}/${rid}-check-${safe}.log"
}

emit_check_log_tail() {
  local log_file="$1"
  local lines="${2:-50}"
  [[ -f "$log_file" ]] || return 0
  echo "==> Last ${lines} lines of ${log_file}:" >&2
  tail -n "$lines" "$log_file" >&2 || true
}

CHECK_LOG_EXCERPT_JS="${HARNESS_ROOT}/scripts/lib/check-log-excerpt.js"

# Actionable failure text from a per-script check log (Node test runner, tsc, eslint, etc.).
extract_check_log_failure_excerpt() {
  local log_file="$1"
  local max_chars="${2:-8000}"
  [[ -f "$log_file" ]] || return 1
  [[ -f "$CHECK_LOG_EXCERPT_JS" ]] || return 1
  node "$CHECK_LOG_EXCERPT_JS" "$log_file" "$max_chars" 2>/dev/null || true
}

# Map a failing test file path to the backlog slice that owns it (if any).
slice_owning_test_path() {
  local test_path="$1"
  local candidate owner candidates=()
  [[ -n "$test_path" ]] || return 1

  candidates+=("$test_path")
  if [[ "$test_path" != apps/* ]]; then
    candidates+=("apps/api/src/${test_path#src/}")
    candidates+=("apps/api/src/$test_path")
  fi

  for candidate in "${candidates[@]}"; do
    owner="$(jq -r --arg p "$candidate" '
      .slices[]
      | select(
          ([.testRequirements.integration[]?, .testRequirements.unit[]?, .testRequirements.component[]?]
            | index($p)) != null
        )
      | .id
    ' "$BACKLOG" 2>/dev/null | head -1)"
    if [[ -n "$owner" ]]; then
      echo "$owner"
      return 0
    fi
  done
  return 1
}

# One-line scope hint when a global npm check failed in another slice's tests.
format_out_of_slice_test_hint() {
  local current_slice="$1"
  local excerpt="$2"
  local paths_json paths path owner hints=""
  [[ -n "$excerpt" ]] || return 0
  paths_json="$(node -e "
    const m = require('${CHECK_LOG_EXCERPT_JS}');
    const text = process.argv[1];
    console.log(JSON.stringify(m.extractFailingTestPaths(text)));
  " "$excerpt" 2>/dev/null || echo '[]')"
  [[ "$paths_json" != "[]" ]] || return 0

  local seen_owners=""
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    owner="$(slice_owning_test_path "$path")"
    if [[ -n "$owner" && "$owner" != "$current_slice" ]]; then
      if echo "$seen_owners" | grep -qF "|${owner}|"; then
        continue
      fi
      seen_owners="${seen_owners}|${owner}|"
      hints+="- Failure in \`${path}\` is owned by slice \`${owner}\`, not \`${current_slice}\`. Fix only if in scope; otherwise revert your changes and signal \`SLICE_DEFER ${owner} <reason>\`."$'\n'
    elif [[ -z "$owner" ]]; then
      hints+="- Failure in \`${path}\` is not listed in any slice \`testRequirements\` — verify scope before editing."$'\n'
    fi
  done < <(echo "$paths_json" | jq -r '.[]?' | sort -u)

  [[ -n "$hints" ]] || return 0
  printf '%s' "**Scope hints (global npm checks run the full suite):**
${hints}"
}

# Build failureExcerpts array for checks.json from failures[].logFile entries.
attach_log_excerpts_to_failures_json() {
  local failures_json="$1"
  local slice_id="${2:-}"
  local max_chars="${3:-8000}"
  local tmp_out entry log_file excerpt scope_hint
  tmp_out="$(mktemp)"

  : >"$tmp_out"
  while IFS= read -r entry; do
    [[ -z "$entry" ]] && continue
    log_file="$(echo "$entry" | jq -r '.logFile // empty')"
    excerpt=""
    scope_hint=""
    if [[ -n "$log_file" && -f "$log_file" ]]; then
      excerpt="$(extract_check_log_failure_excerpt "$log_file" "$max_chars")"
      if [[ -n "$excerpt" && -n "$slice_id" ]]; then
        scope_hint="$(format_out_of_slice_test_hint "$slice_id" "$excerpt")"
      fi
    fi
    echo "$entry" | jq -c \
      --arg excerpt "$excerpt" \
      --arg scopeHint "$scope_hint" \
      --arg logBase "$(basename "${log_file:-}")" \
      '. + (
        if $excerpt != "" then {logExcerpt: $excerpt, logBasename: $logBase} else {} end
      ) + (
        if $scopeHint != "" then {scopeHint: $scopeHint} else {} end
      )' >>"$tmp_out"
  done < <(echo "$failures_json" | jq -c '.[]?')

  if [[ -s "$tmp_out" ]]; then
    jq -s '.' "$tmp_out"
  else
    echo "$failures_json"
  fi
  rm -f "$tmp_out"
}

get_check_command_timeout_ms() {
  local script="${1:-}"
  local config_timeout env_key

  if [[ -n "${AIH_CHECK_TIMEOUT_MS:-}" ]]; then
    echo "$AIH_CHECK_TIMEOUT_MS"
    return 0
  fi

  if [[ -n "$script" ]]; then
    env_key="AIH_CHECK_TIMEOUT_${script//[:]/_}_MS"
    if [[ -n "${!env_key:-}" ]]; then
      echo "${!env_key}"
      return 0
    fi
  fi

  config_timeout="$(jq -r --arg s "$script" \
    '.computationalChecks.commandTimeouts[$s] // .computationalChecks.commandTimeoutMs // empty' \
    "$LOOP_CONFIG" 2>/dev/null || true)"
  if [[ -n "$config_timeout" && "$config_timeout" != "null" ]]; then
    echo "$config_timeout"
    return 0
  fi

  echo "$CHECK_COMMAND_TIMEOUT_DEFAULT_MS"
}

# Markdown bullet list of computational check timeouts for agent prompts.
format_check_timeout_budgets_block() {
  jq -r '
    (.computationalChecks.commandTimeoutMs // 600000) as $default |
    "**Harness command timeout budgets** (from `ai-harness/workflows/ralph-loop.json`):\n",
    "- default npm script: \($default / 1000)s",
    (.computationalChecks.commandTimeouts // {} | to_entries | sort_by(.key)[] |
      "- \(.key): \(.value / 1000)s"),
    "- override env: `AIH_CHECK_TIMEOUT_MS` or `AIH_CHECK_TIMEOUT_<script>_MS` (see `ai-harness/README.md`)"
  ' "$LOOP_CONFIG" 2>/dev/null || cat <<'EOF'
**Harness command timeout budgets:** default 600s per npm script (see `ai-harness/workflows/ralph-loop.json`)
EOF
}

check_timeout_message() {
  local timeout_ms="$1"
  local label="${2:-check}"
  local timeout_sec=$(( timeout_ms / 1000 ))
  echo "ERROR: ${label} timed out after ${timeout_ms}ms (${timeout_sec}s) — process tree terminated" >&2
}

kill_process_tree() {
  local pid="$1"
  local sig="${2:-TERM}"
  local child

  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi

  while IFS= read -r child; do
    [[ -z "$child" ]] && continue
    kill_process_tree "$child" "$sig"
  done < <(pgrep -P "$pid" 2>/dev/null || true)

  if [[ "$sig" == "KILL" ]]; then
    kill -KILL "$pid" 2>/dev/null || true
  else
    kill -TERM "$pid" 2>/dev/null || true
  fi
}

wait_cmd_with_timeout_ms() {
  local cmd_pid="$1"
  local timeout_ms="$2"
  local label="${3:-command}"
  local started_ms=$(( $(date +%s) * 1000 ))
  local deadline=$(( started_ms + timeout_ms ))
  local last_heartbeat_ms=$started_ms
  local heartbeat_ms
  heartbeat_ms="$(get_check_heartbeat_ms)"

  while kill -0 "$cmd_pid" 2>/dev/null; do
    local now_ms=$(( $(date +%s) * 1000 ))
    if (( now_ms >= deadline )); then
      kill_process_tree "$cmd_pid" TERM
      sleep 2
      kill_process_tree "$cmd_pid" KILL
      wait "$cmd_pid" 2>/dev/null || true
      return "$AGENT_TIMEOUT_EXIT"
    fi
    if (( now_ms - last_heartbeat_ms >= heartbeat_ms )); then
      local elapsed_sec=$(( (now_ms - started_ms) / 1000 ))
      local budget_sec=$(( timeout_ms / 1000 ))
      echo "==> still running: ${label} (${elapsed_sec}s / ${budget_sec}s)" >&2
      last_heartbeat_ms=$now_ms
    fi
    sleep $(( CHECK_COMMAND_TIMEOUT_POLL_MS / 1000 ))
  done

  wait "$cmd_pid"
}

# Run a check command with wall-clock timeout; streams stdout/stderr live.
# Usage: run_check_with_timeout_ms MS [--log FILE] [--label LABEL] [--fn] cmd [args...]
run_check_with_timeout_ms() {
  local timeout_ms="$1"
  shift
  local log_file="" label="" use_fn=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --log)
        log_file="$2"
        shift 2
        ;;
      --label)
        label="$2"
        shift 2
        ;;
      --fn)
        use_fn=true
        shift
        ;;
      *)
        break
        ;;
    esac
  done

  [[ -n "$label" ]] || label="${*:-command}"

  local fifo tee_pid status cmd_pid
  fifo="$(mktemp -u "${TMPDIR:-/tmp}/aih-check.XXXXXX")"
  mkfifo "$fifo"

  if [[ -n "$log_file" ]]; then
    mkdir -p "$(dirname "$log_file")"
    tee "$log_file" < "$fifo" &
    tee_pid=$!
  else
    tee < "$fifo" &
    tee_pid=$!
  fi

  if [[ "$use_fn" == true ]]; then
    local fn="$1"
    shift
    ( "$fn" "$@" ) > "$fifo" 2>&1 &
    cmd_pid=$!
  else
    # Line-buffered stdout helps integration tests stream per-spec output.
    env PYTHONUNBUFFERED=1 "$@" > "$fifo" 2>&1 &
    cmd_pid=$!
  fi

  set +e
  wait_cmd_with_timeout_ms "$cmd_pid" "$timeout_ms" "$label"
  status=$?
  set -e

  wait "$tee_pid" 2>/dev/null || true
  rm -f "$fifo"

  if [[ "$status" -eq "$AGENT_TIMEOUT_EXIT" ]] && [[ -n "$log_file" ]]; then
    emit_check_log_tail "$log_file" 50
  fi

  return "$status"
}

get_agent_timeout_ms() {
  local config="${1:-$LOOP_CONFIG}"
  if [[ -n "${AIH_AGENT_TIMEOUT_MS:-}" ]]; then
    echo "$AIH_AGENT_TIMEOUT_MS"
    return
  fi
  jq -r ".agent.timeoutMs // ${AGENT_TIMEOUT_DEFAULT_MS}" "$config"
}

get_agent_idle_timeout_ms() {
  local config="${1:-${AIH_HARNESS_CONFIG:-$LOOP_CONFIG}}"
  if [[ -n "${AIH_AGENT_IDLE_TIMEOUT_MS:-}" ]]; then
    echo "$AIH_AGENT_IDLE_TIMEOUT_MS"
    return
  fi
  jq -r ".agent.idleTimeoutMs // ${AGENT_IDLE_TIMEOUT_DEFAULT_MS}" "$config"
}

get_agent_signal_grace_ms() {
  local config="${1:-${AIH_HARNESS_CONFIG:-$LOOP_CONFIG}}"
  if [[ -n "${AIH_AGENT_SIGNAL_GRACE_MS:-}" ]]; then
    echo "$AIH_AGENT_SIGNAL_GRACE_MS"
    return
  fi
  jq -r ".agent.signalGraceMs // ${AGENT_SIGNAL_GRACE_DEFAULT_MS}" "$config"
}

get_agent_result_grace_ms() {
  local config="${1:-${AIH_HARNESS_CONFIG:-$LOOP_CONFIG}}"
  if [[ -n "${AIH_AGENT_RESULT_GRACE_MS:-}" ]]; then
    echo "$AIH_AGENT_RESULT_GRACE_MS"
    return
  fi
  jq -r ".agent.resultGraceMs // ${AGENT_RESULT_GRACE_DEFAULT_MS}" "$config"
}

agent_completion_signals_csv() {
  local config="${1:-${AIH_HARNESS_CONFIG:-$LOOP_CONFIG}}"
  jq -r '[.signals[]? // empty] | unique | join(",")' "$config"
}

agent_timeout_message() {
  local timeout_ms="$1"
  local timeout_min=$(( timeout_ms / 60000 ))
  echo "ERROR: Agent timed out after ${timeout_ms}ms (${timeout_min}m)"
}

agent_idle_timeout_message() {
  local idle_ms="$1"
  local idle_min=$(( idle_ms / 60000 ))
  echo "ERROR: Agent timed out after ${idle_ms}ms idle (no stream output for ${idle_min}m)"
}

agent_stream_enabled() {
  [[ "${AIH_STREAM_AGENT:-1}" != "0" ]]
}

run_agent_uses_stream_json() {
  local arg
  for arg in "$@"; do
    [[ "$arg" == "stream-json" ]] && return 0
  done
  return 1
}

agent_verbose_enabled() {
  [[ "${AIH_AGENT_VERBOSE:-1}" == "1" ]]
}

agent_output_format_args() {
  if agent_stream_enabled; then
    echo '--output-format stream-json --stream-partial-output'
  else
    echo '--output-format text'
  fi
}

run_command_with_timeout_ms() {
  local timeout_ms="$1"
  shift
  local cmd_pid

  "$@" &
  cmd_pid=$!

  set +e
  wait_cmd_with_timeout_ms "$cmd_pid" "$timeout_ms"
  local status=$?
  set -e
  return "$status"
}

run_agent_with_timeout_ms() {
  local timeout_ms="$1"
  local outfile="$2"
  shift 2
  local status timeout_msg fifo tee_pid
  local -a stream_cmd

  if [[ -n "$outfile" ]] && agent_stream_enabled && run_agent_uses_stream_json "$@"; then
    local idle_ms signal_grace_ms result_grace_ms signals_csv harness_config
    harness_config="${AIH_HARNESS_CONFIG:-$LOOP_CONFIG}"
    idle_ms="$(get_agent_idle_timeout_ms "$harness_config")"
    signal_grace_ms="$(get_agent_signal_grace_ms "$harness_config")"
    result_grace_ms="$(get_agent_result_grace_ms "$harness_config")"
    signals_csv="$(agent_completion_signals_csv "$harness_config")"
    stream_cmd=(node "${HARNESS_ROOT}/scripts/lib/stream-agent-output.js" \
      --outfile "$outfile" \
      --idle-timeout-ms "$idle_ms" \
      --max-timeout-ms "$timeout_ms" \
      --signal-grace-ms "$signal_grace_ms" \
      --result-grace-ms "$result_grace_ms")
    if [[ -n "$signals_csv" ]]; then
      stream_cmd+=(--signals "$signals_csv")
    fi
    if agent_verbose_enabled; then
      stream_cmd+=(--verbose)
    fi
    stream_cmd+=(-- "$@")
    set +e
    "${stream_cmd[@]}"
    status=$?
    set -e
    if [[ "$status" -eq "$AGENT_TIMEOUT_EXIT" ]] && [[ -n "$outfile" ]] && ! grep -q "ERROR: Agent timed out" "$outfile" 2>/dev/null; then
      timeout_msg="$(agent_timeout_message "$timeout_ms")"
      echo "$timeout_msg" | tee -a "$outfile" >&2
    fi
    return "$status"
  fi

  if [[ -n "$outfile" ]]; then
    fifo="$(mktemp -u "${TMPDIR:-/tmp}/aih-agent.XXXXXX")"
    mkfifo "$fifo"
    tee "$outfile" < "$fifo" &
    tee_pid=$!
    set +e
    run_command_with_timeout_ms "$timeout_ms" "$@" > "$fifo"
    status=$?
    set -e
    wait "$tee_pid" 2>/dev/null || true
    rm -f "$fifo"
    if [[ "$status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
      timeout_msg="$(agent_timeout_message "$timeout_ms")"
      echo "$timeout_msg" | tee -a "$outfile" >&2
    fi
    return "$status"
  fi

  set +e
  run_command_with_timeout_ms "$timeout_ms" "$@"
  status=$?
  set -e
  if [[ "$status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
    agent_timeout_message "$timeout_ms" >&2
  fi
  return "$status"
}

run_id() {
  date -u +"%Y%m%dT%H%M%SZ"
}

ensure_runs_dir() {
  mkdir -p "$RUNS_DIR"
}

# Canonical UI screenshot dir: ai-harness/generated/runs/screenshots/<slice>/<phase>/
# phase: implementer | browser-test
screenshot_dir_for_slice() {
  local slice_id="$1"
  local phase="${2:-implementer}"
  echo "${SCREENSHOTS_ROOT}/${slice_id}/${phase}"
}

ensure_screenshot_dir() {
  local dir="$1"
  ensure_runs_dir
  mkdir -p "$dir"
}

# Markdown block injected into implementer/tester prompts via build-prompt.sh
format_screenshot_dir_block() {
  local slice_id="$1"
  local phase="${2:-implementer}"
  local dir example_ts example_name
  dir="$(screenshot_dir_for_slice "$slice_id" "$phase")"
  example_ts="$(date -u +"%Y%m%dT%H%M%SZ")"
  example_name="${example_ts}-page-slug.png"
  cat <<EOF
**Screenshot directory (required — do not save elsewhere):** \`${dir}\`

- \`mkdir -p "${dir}"\` before the first capture (harness may pre-create this path)
- **cursor-ide-browser** \`browser_take_screenshot\`: set \`filename\` to an **absolute path** under this directory, e.g. \`${dir}/${example_name}\`
- **Playwright MCP**: pass the same directory when the tool accepts a path; otherwise **move/copy** captures here — never leave screenshots in \`.playwright-mcp/\`, repo root, or \`/tmp\`
- Filename pattern: \`<UTC-timestamp>-<page-or-case-slug>.png\` (lowercase, hyphens; e.g. \`${example_name}\`)
- List every saved path in your summary and in \`ai-harness/state/progress.md\`
EOF
}

playwright_output_path_for_slice() {
  local slice_id="$1"
  echo "${PLAYWRIGHT_UI_SCENARIOS_DIR}/${slice_id}.spec.ts"
}

ux_bugs_path_for_slice_run() {
  local slice_id="$1"
  local run_id="$2"
  echo "${UX_BUGS_ROOT}/${slice_id}/${run_id}.json"
}

ensure_playwright_regression_dirs() {
  local slice_id="$1"
  local run_id="$2"
  ensure_runs_dir
  mkdir -p "${PLAYWRIGHT_UI_SCENARIOS_DIR}"
  mkdir -p "${UX_BUGS_ROOT}/${slice_id}"
  if [[ ! -f "$PLAYWRIGHT_REGRESSION_INDEX" ]]; then
    echo '{"slices":{}}' >"$PLAYWRIGHT_REGRESSION_INDEX"
  fi
}

format_playwright_codegen_block() {
  local slice_id="$1"
  local run_id="$2"
  local spec_path ux_path
  spec_path="$(playwright_output_path_for_slice "$slice_id")"
  ux_path="$(ux_bugs_path_for_slice_run "$slice_id" "$run_id")"
  cat <<EOF
## Post-verification — UX audit and Playwright regression (full phase only)

After all \`TC-*\` cases complete:

1. **UX audit** — review each screenshot per \`ai-harness/skills/ui-ux-testing/SKILL.md\`; log \`UX-${slice_id}-NNN\` bugs not already \`TC-*: FAIL\`
2. **Write UX bugs JSON:** \`${ux_path}\` (schema: \`ai-harness/schemas/ux-bugs.schema.json\`)
3. **Playwright codegen** — create or update \`${spec_path}\` per \`ai-harness/docs/playwright-regression.md\`
4. Emit a plain line (no markdown/backticks): \`playwright-regression: ${spec_path} (N tests)\` before the signal line
5. P0/P1 UX bugs block \`BROWSER_TEST_PASS\` even when all \`TC-*\` cases pass
EOF
}

browser_output_has_ux_blockers() {
  local text_file="$1"
  [[ -f "$text_file" ]] || return 1
  grep -qE 'UX-[a-z0-9-]+-[0-9]{3}:[[:space:]]*P[01]' "$text_file" 2>/dev/null
}

browser_output_has_actionable_failures() {
  local text_file="$1"
  [[ -f "$text_file" ]] || return 1
  if grep -qE 'TC-[A-Z0-9][A-Z0-9-]*:[[:space:]]*FAIL' "$text_file" 2>/dev/null; then
    return 0
  fi
  browser_output_has_ux_blockers "$text_file"
}

# Coerce shell text to valid JSON for jq --argjson (fallback when empty/invalid).
jq_json_or_default() {
  local value="${1:-}"
  local default="${2:-null}"
  if [[ -z "$value" ]]; then
    printf '%s' "$default"
    return
  fi
  if jq -e . >/dev/null 2>&1 <<<"$value"; then
    printf '%s' "$value"
  else
    printf '%s' "$default"
  fi
}

jq_number_or_default() {
  local value="${1:-}"
  local default="${2:-0}"
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$default"
  fi
}

parse_playwright_regression_from_output() {
  local text_file="$1"
  local line spec count
  [[ -f "$text_file" ]] || return 1
  line="$(grep -E 'playwright-regression:' "$text_file" 2>/dev/null | tail -1 || true)"
  [[ -n "$line" ]] || return 1
  line="$(echo "$line" | sed -E 's/^[`[:space:]]*//; s/[`[:space:]]*$//')"
  spec="$(echo "$line" | sed -E 's/^playwright-regression:[[:space:]]*([^ (]+).*/\1/')"
  count="$(echo "$line" | sed -nE 's/.*\(([0-9]+) tests?\).*/\1/p')"
  [[ -z "$count" ]] && count="0"
  [[ -z "$spec" || "$spec" == "$line" ]] && return 1
  printf '%s\t%s\n' "$spec" "$count"
}

extract_source_tc_ids_from_output() {
  local text_file="$1"
  [[ -f "$text_file" ]] || return 1
  grep -oE 'TC-[A-Z0-9][A-Z0-9-]*:[[:space:]]*PASS' "$text_file" 2>/dev/null \
    | sed -E 's/:[[:space:]]*PASS$//' \
    | sort -u
}

parse_ux_bugs_summary_from_output() {
  local text_file="$1"
  local max_chars="${2:-8000}"
  [[ -f "$text_file" ]] || return 1
  grep -E '^UX-[a-z0-9-]+-[0-9]{3}:' "$text_file" 2>/dev/null | head -c "$max_chars" || true
}

update_playwright_regression_index() {
  local slice_id="$1"
  local spec_path="$2"
  local run_id="$3"
  local test_count
  test_count="$(jq_number_or_default "${4:-0}")"
  local tc_ids_json
  tc_ids_json="$(jq_json_or_default "${5:-[]}" '[]')"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  [[ -f "$PLAYWRIGHT_REGRESSION_INDEX" ]] || echo '{"slices":{}}' >"$PLAYWRIGHT_REGRESSION_INDEX"
  local tmp
  tmp="$(mktemp)"
  jq \
    --arg id "$slice_id" \
    --arg spec "$spec_path" \
    --arg run "$run_id" \
    --argjson count "$test_count" \
    --argjson tcIds "$tc_ids_json" \
    --arg ts "$ts" \
    '.slices[$id] = {
      specPath: $spec,
      lastRunId: $run,
      testCount: $count,
      sourceTcIds: $tcIds,
      updatedAt: $ts
    }' "$PLAYWRIGHT_REGRESSION_INDEX" >"$tmp"
  mv "$tmp" "$PLAYWRIGHT_REGRESSION_INDEX"
}

enrich_browser_test_report_json() {
  local base_json="$1"
  local text_file="$2"
  local slice_id="$3"
  local run_id="$4"
  local ux_json_file
  ux_json_file="$(ux_bugs_path_for_slice_run "$slice_id" "$run_id")"
  local ux_bugs_json='[]'
  if [[ -f "$ux_json_file" ]]; then
    ux_bugs_json="$(jq_json_or_default "$(jq -c '.bugs // []' "$ux_json_file" 2>/dev/null || true)" '[]')"
  fi
  local playwright_spec="" playwright_count=0 parse_line=""
  if parse_line="$(parse_playwright_regression_from_output "$text_file" 2>/dev/null)"; then
    playwright_spec="$(echo "$parse_line" | cut -f1)"
    playwright_count="$(jq_number_or_default "$(echo "$parse_line" | cut -f2)")"
  fi
  jq \
    --argjson uxBugs "$ux_bugs_json" \
    --arg playwrightSpec "$playwright_spec" \
    --argjson playwrightTestCount "$playwright_count" \
    '. + {
      uxBugs: $uxBugs,
      playwrightSpec: (if $playwrightSpec == "" then null else $playwrightSpec end),
      playwrightTestCount: $playwrightTestCount
    }' <<<"$base_json"
}

all_slices_pass() {
  local pending
  pending="$(jq '[.slices[] | select(.passes == false)] | length' "$BACKLOG")"
  [[ "$pending" -eq 0 ]]
}

ensure_loop_state_file() {
  if [[ ! -f "$LOOP_STATE" ]]; then
    echo '{}' > "$LOOP_STATE"
  fi
}

loop_consume_override_on_pick() {
  jq -r '.loop.consumeOverrideOnPick // true' "$LOOP_CONFIG"
}

get_loop_slice_override() {
  ensure_loop_state_file
  local next_id passes
  next_id="$(jq -r '.nextSliceId // empty' "$LOOP_STATE" 2>/dev/null)"
  [[ -n "$next_id" && "$next_id" != "null" ]] || return 1
  passes="$(get_slice_field "$next_id" passes 2>/dev/null || echo "true")"
  if [[ "$passes" == "false" ]]; then
    echo "$next_id"
    return 0
  fi
  return 1
}

set_loop_slice_override() {
  local slice_id="$1"
  local reason="$2"
  local set_by="${3:-manual}"
  local ts tmp
  ensure_loop_state_file
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  tmp="$(mktemp)"
  jq -n \
    --arg id "$slice_id" \
    --arg reason "$reason" \
    --arg setBy "$set_by" \
    --arg setAt "$ts" \
    '{nextSliceId: $id, reason: $reason, setAt: $setAt, setBy: $setBy}' \
    > "$tmp" && mv "$tmp" "$LOOP_STATE"
}

clear_loop_slice_override() {
  echo '{}' > "$LOOP_STATE"
}

get_loop_slice_override_info() {
  ensure_loop_state_file
  jq -c '.' "$LOOP_STATE" 2>/dev/null || echo '{}'
}

append_slice_history() {
  local slice_id="$1"
  local kind="$2"
  local reason="$3"
  local source="$4"
  local related_slice="${5:-}"
  local ts tmp
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  tmp="$(mktemp)"
  if [[ -n "$related_slice" ]]; then
    jq --arg id "$slice_id" --arg at "$ts" --arg kind "$kind" --arg reason "$reason" --arg source "$source" --arg related "$related_slice" '
      .slices |= map(
        if .id == $id then
          .history = ((.history // []) + [{
            at: $at,
            kind: $kind,
            reason: $reason,
            source: $source,
            relatedSlice: $related
          }])
          | if (.history | length) > 20 then .history = .history[-20:] else . end
        else .
        end
      )
    ' "$BACKLOG" > "$tmp" && mv "$tmp" "$BACKLOG"
  else
    jq --arg id "$slice_id" --arg at "$ts" --arg kind "$kind" --arg reason "$reason" --arg source "$source" '
      .slices |= map(
        if .id == $id then
          .history = ((.history // []) + [{
            at: $at,
            kind: $kind,
            reason: $reason,
            source: $source
          }])
          | if (.history | length) > 20 then .history = .history[-20:] else . end
        else .
        end
      )
    ' "$BACKLOG" > "$tmp" && mv "$tmp" "$BACKLOG"
  fi
}

mark_slice_reopened() {
  local slice_id="$1"
  local reason="$2"
  local source="$3"
  local kind="${4:-reopened}"
  local related_slice="${5:-}"
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$slice_id" '
    .slices |= map(if .id == $id then .passes = false else . end)
  ' "$BACKLOG" > "$tmp" && mv "$tmp" "$BACKLOG"
  if [[ -n "$related_slice" ]]; then
    append_slice_history "$slice_id" "$kind" "$reason" "$source" "$related_slice"
  else
    append_slice_history "$slice_id" "$kind" "$reason" "$source"
  fi
}

format_slice_history_block() {
  local slice_id="$1"
  local count block
  count="$(jq -r --arg id "$slice_id" '
    [.slices[] | select(.id == $id) | (.history // []) | length] | .[0] // 0
  ' "$BACKLOG")"
  [[ "$count" -gt 0 ]] || return 0

  block="$(jq -r --arg id "$slice_id" '
    (.slices[] | select(.id == $id) | .history // [])[-5:]
    | .[]
    | "- \(.at) | \(.kind) | \(.source): \(.reason)\(if .relatedSlice then " (related: \(.relatedSlice))" else "" end)"
  ' "$BACKLOG")"
  [[ -n "$block" ]] || return 0

  cat <<EOF
## Slice history

Recent reopen/failure context for this slice (newest last):

${block}
EOF
}

record_iteration_failure() {
  local slice_id="$1"
  local history_kind="$2"
  local progress_status="$3"
  local guardrail_msg="$4"
  append_guardrail "$slice_id" "$guardrail_msg"
  append_slice_history "$slice_id" "$history_kind" "$guardrail_msg" "harness"
  append_progress "$slice_id" "$progress_status"
}

pick_next_slice_id() {
  local override_id
  override_id="$(get_loop_slice_override 2>/dev/null || true)"
  if [[ -n "$override_id" ]]; then
    if [[ "$(loop_consume_override_on_pick)" == "true" ]]; then
      clear_loop_slice_override
    fi
    echo "$override_id"
    return 0
  fi
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

test_case_gate_mode() {
  if [[ "${AIH_SKIP_TESTGEN_GATE:-}" == "1" ]]; then
    echo "optional"
    return
  fi
  jq -r '.testCaseGate.mode // "optional"' "$LOOP_CONFIG"
}

slice_missing_test_case_tags() {
  local slice_id="$1"
  local ref
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    if ! requirement_tag_test_cases_current "$ref"; then
      echo "$ref"
    fi
  done < <(slice_requirement_tag_refs "$slice_id")
}

mark_slice_passed() {
  local slice_id="$1"
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$slice_id" '
    .slices |= map(if .id == $id then .passes = true else . end)
  ' "$BACKLOG" > "$tmp" && mv "$tmp" "$BACKLOG"
}

test_case_artifact_path() {
  local requirement_tag="$1"
  printf 'docs/test-cases/items/%s.json' "$requirement_tag"
}

test_case_artifact_abs() {
  local requirement_tag="$1"
  echo "${REPO_ROOT}/$(test_case_artifact_path "$requirement_tag")"
}

test_case_stale_artifact_path() {
  local requirement_tag="$1"
  printf 'docs/test-cases/items/%s.stale.json' "$requirement_tag"
}

test_case_stale_artifact_abs() {
  local requirement_tag="$1"
  echo "${REPO_ROOT}/$(test_case_stale_artifact_path "$requirement_tag")"
}

# Legacy: drift used to mv artifacts to .stale.json — restore so the agent can review in place.
ensure_test_case_artifact_restored() {
  local requirement_tag="$1"
  local artifact_path stale_path
  artifact_path="$(test_case_artifact_abs "$requirement_tag")"
  stale_path="$(test_case_stale_artifact_abs "$requirement_tag")"
  if [[ ! -f "$artifact_path" && -f "$stale_path" ]]; then
    cp -f "$stale_path" "$artifact_path"
    echo "==> ${requirement_tag}: restored legacy .stale.json to $(test_case_artifact_path "$requirement_tag")"
  fi
}

testgen_regeneration_mode() {
  jq -r '.regeneration.mode // "incremental"' "$TESTGEN_CONFIG" 2>/dev/null || echo "incremental"
}

format_existing_artifact_review_block() {
  local requirement_tag="$1"
  local artifact_path artifact_abs mode case_count id_list stored_fp
  artifact_path="$(test_case_artifact_path "$requirement_tag")"
  artifact_abs="$(test_case_artifact_abs "$requirement_tag")"
  mode="$(testgen_regeneration_mode)"

  if [[ ! -f "$artifact_abs" ]]; then
    return 0
  fi

  if [[ "$mode" == "full" ]]; then
    cat <<EOF
## Existing artifact (reference)

An artifact already exists at \`${artifact_path}\`. Regeneration mode is **full** — rewrite from current docs. You may use the existing file as reference but replace content as needed.

EOF
    return 0
  fi

  case_count="$(jq '.cases | length' "$artifact_abs")"
  id_list="$(jq -r '.cases[].id' "$artifact_abs" | paste -sd ', ' -)"
  stored_fp="$(jq -r --arg id "$requirement_tag" '.tags[$id].docFingerprint // ""' "$TEST_CASE_INDEX")"

  cat <<EOF
## Review and update existing artifact

The test case artifact at \`${artifact_path}\` is **out of date** (\`test-case-index.json\` marks this tag \`current: false\` — docs changed since last generation).

**Read the existing file first.** Update only what current docs require — do not rewrite from scratch.

### Review rules

1. **Keep** cases that still match current docs; edit only affected fields (\`traceability\`, \`title\`, \`preconditions\`, \`steps\`, \`expected\`, \`edgeCase\`, \`priority\`).
2. **Add** cases for new doc requirements or coverage gaps (self-check below). Append new IDs; do not renumber existing ones.
3. **Remove** cases only when docs explicitly drop that scenario.
4. Set \`docFingerprint\` to the value in this prompt and refresh \`generatedAt\`.
$( [[ -n "$stored_fp" && "$stored_fp" != "null" ]] && printf '5. Index stored fingerprint: `%s` (artifact may still carry an older `docFingerprint`).\n' "$stored_fp" )

### Existing artifact summary

- **Path:** \`${artifact_path}\`
- **Case count:** ${case_count}
- **Case IDs:** ${id_list}

EOF
}

format_regeneration_finish_hint() {
  local requirement_tag="$1"
  local artifact_abs mode
  artifact_abs="$(test_case_artifact_abs "$requirement_tag")"
  mode="$(testgen_regeneration_mode)"

  if [[ -f "$artifact_abs" && "$mode" == "incremental" ]]; then
    echo "Finish in **one pass** — review the existing artifact against docs; update only what changed. Generate specs only — no implementation."
    return 0
  fi
  echo "Finish in **one pass**. Generate specs only — no implementation."
}

valid_requirement_tag() {
  local tag="$1"
  [[ "$tag" =~ ^(AC|FR|BR|NFR)-[0-9]+$ ]]
}

require_valid_requirement_tag() {
  local tag="$1"
  if ! valid_requirement_tag "$tag"; then
    echo "ERROR: invalid requirement tag: ${tag} (expected AC-*, FR-*, BR-*, or NFR-*)" >&2
    exit 1
  fi
}

slices_for_requirement_tag() {
  local requirement_tag="$1"
  jq -r --arg tag "$requirement_tag" '
    .slices[] | select(.acceptance[]? == $tag) |
    "- `\(.id)`: \(.description // "") (acceptance: \(.acceptance | join(", ")))"
  ' "$BACKLOG" 2>/dev/null || true
}

format_enhancement_artifact_block() {
  local requirement_tag="$1"
  local artifact_path artifact_abs case_count id_list
  artifact_path="$(test_case_artifact_path "$requirement_tag")"
  artifact_abs="$(test_case_artifact_abs "$requirement_tag")"

  if [[ ! -f "$artifact_abs" ]]; then
    cat <<EOF
## Artifact status

No test case artifact exists yet at \`${artifact_path}\`. Create one per docs, validation policy, and the enhancement instructions below.

EOF
    return 0
  fi

  case_count="$(jq '.cases | length' "$artifact_abs")"
  id_list="$(jq -r '.cases[].id' "$artifact_abs" | paste -sd ', ' -)"

  cat <<EOF
## Existing artifact (incremental update)

**Read the existing file first** at \`${artifact_path}\`. Apply the enhancement instructions below — do not rewrite from scratch.

### Update rules

1. **Keep** cases that remain valid; edit only affected fields.
2. **Add** cases per instructions; append new IDs; do not renumber existing ones.
3. **Remove** cases only when instructions or docs explicitly drop that scenario.
4. Set \`docFingerprint\` to the value in this prompt and refresh \`generatedAt\`.

### Existing artifact summary

- **Path:** \`${artifact_path}\`
- **Case count:** ${case_count}
- **Case IDs:** ${id_list}

EOF
}

format_testgen_enhancement_block() {
  local requirement_tag="$1"
  local instructions="$2"
  local extra_context="${3:-}"

  local slices_block
  slices_block="$(slices_for_requirement_tag "$requirement_tag")"
  if [[ -z "$slices_block" ]]; then
    slices_block="_(no backlog slices reference this tag)_"
  fi

  cat <<EOF
## Enhancement request (human-directed)

Apply these improvements to the test case artifact. This is **ad-hoc** — not doc-drift driven.
Keep valid cases; add, edit, or remove per instructions. Append new case IDs; do not renumber.

### Instructions

${instructions}

### Related implementation slices

${slices_block}

EOF

  format_enhancement_artifact_block "$requirement_tag"

  if [[ -n "$extra_context" ]]; then
    cat <<EOF
### Extra context paths (read as needed)

${extra_context}

EOF
  fi
}

requirement_tag_priority() {
  local tag="$1"
  local num
  if [[ "$tag" =~ ^AC-([0-9]+)$ ]]; then
    num="${BASH_REMATCH[1]}"
    echo $((10#$num))
  elif [[ "$tag" =~ ^FR-([0-9]+)$ ]]; then
    num="${BASH_REMATCH[1]}"
    echo $((100 + 10#$num))
  elif [[ "$tag" =~ ^BR-([0-9]+)$ ]]; then
    num="${BASH_REMATCH[1]}"
    echo $((200 + 10#$num))
  elif [[ "$tag" =~ ^NFR-([0-9]+)$ ]]; then
    num="${BASH_REMATCH[1]}"
    echo $((300 + 10#$num))
  else
    echo 999
  fi
}

all_requirement_tag_ids() {
  {
    jq -r '.slices[].acceptance[]?' "$BACKLOG" 2>/dev/null || true
    jq -r '
      [
        (.catalog.FR // []),
        (.catalog.BR // []),
        (.catalog.AC // []),
        (.catalog.NFR // [])
      ] | add | .[]
    ' "$TESTGEN_DOCS_MAP" 2>/dev/null || true
  } | sort -u
}

all_requirement_tags_sorted() {
  local tag prio
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    prio="$(requirement_tag_priority "$tag")"
    printf '%05d\t%s\n' "$prio" "$tag"
  done < <(all_requirement_tag_ids) | sort -n | cut -f2-
}

requirement_tag_test_cases_current() {
  local requirement_tag="$1"
  local current
  current="$(jq -r --arg id "$requirement_tag" '.tags[$id].current // false' "$TEST_CASE_INDEX")"
  [[ "$current" == "true" ]]
}

slice_test_cases_current() {
  local slice_id="$1"
  local ref
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    if ! requirement_tag_test_cases_current "$ref"; then
      return 1
    fi
  done < <(slice_requirement_tag_refs "$slice_id")
  return 0
}

all_test_cases_current() {
  local tag
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    if ! requirement_tag_test_cases_current "$tag"; then
      return 1
    fi
  done < <(all_requirement_tags_sorted)
  return 0
}

pick_next_testgen_requirement_tag() {
  local tag
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    if ! requirement_tag_test_cases_current "$tag"; then
      echo "$tag"
      return 0
    fi
  done < <(all_requirement_tags_sorted)
  echo ""
}

mark_test_cases_current() {
  local requirement_tag="$1"
  local fingerprint="$2"
  local generated_at="${3:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$requirement_tag" --arg fp "$fingerprint" --arg ts "$generated_at" '
    .tags[$id] = {
      current: true,
      docFingerprint: $fp,
      generatedAt: $ts
    }
  ' "$TEST_CASE_INDEX" > "$tmp" && mv "$tmp" "$TEST_CASE_INDEX"
  mark_slices_stale_for_tag "$requirement_tag"
}

reset_requirement_tag_on_doc_drift() {
  local requirement_tag="$1"
  local live_fp="$2"
  ensure_test_case_artifact_restored "$requirement_tag"
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$requirement_tag" --arg fp "$live_fp" '
    .tags[$id] = {
      current: false,
      docFingerprint: $fp,
      generatedAt: null
    }
  ' "$TEST_CASE_INDEX" > "$tmp" && mv "$tmp" "$TEST_CASE_INDEX"
  append_guardrail "$requirement_tag" "Docs changed — run TestGen before Ralph (index current=false; fingerprint=${live_fp})"
}

mark_slices_stale_for_tag() {
  local requirement_tag="$1"
  local pi_tmp slice_id
  local -a stale_ids=()
  while IFS= read -r slice_id; do
    [[ -z "$slice_id" ]] && continue
    stale_ids+=("$slice_id")
  done < <(jq -r --arg ref "$requirement_tag" '
    [.slices[]
      | select((.acceptance // [] | index($ref)) and (.reverifyOnDrift // true))
      | .id] | .[]
  ' "$BACKLOG")
  pi_tmp="$(mktemp)"
  jq --arg ref "$requirement_tag" '
    .slices |= map(
      if ((.acceptance // [] | index($ref)) and (.reverifyOnDrift // true)) then .passes = false else . end
    )
  ' "$BACKLOG" > "$pi_tmp" && mv "$pi_tmp" "$BACKLOG"
  for slice_id in "${stale_ids[@]}"; do
    append_slice_history "$slice_id" "drift" "Doc drift for ${requirement_tag} — reverify after TestGen" "harness"
  done
}

playwright_scope_for_checks() {
  jq -r '.computationalChecks.playwrightScope // "full"' "$LOOP_CONFIG"
}

playwright_full_every_n() {
  jq -r '.computationalChecks.playwrightFullEveryN // 0' "$LOOP_CONFIG"
}

get_check_profile() {
  local profile="${AIH_CHECK_PROFILE:-}"
  if [[ -z "$profile" ]]; then
    profile="$(jq -r '.computationalChecks.gateProfile // "full"' "$LOOP_CONFIG")"
  fi
  echo "$profile"
}

profile_includes_script() {
  local profile="$1"
  local script="$2"
  jq -e --arg p "$profile" --arg s "$script" '
    .computationalChecks.profiles[$p] | index($s)
  ' "$LOOP_CONFIG" >/dev/null 2>&1
}

resolve_playwright_spec_for_slice() {
  local slice_id="$1"
  local slice_json spec
  slice_json="$(get_slice_json "$slice_id")"
  [[ -z "$slice_json" || "$slice_json" == "null" ]] && return 1

  spec="$(echo "$slice_json" | jq -r '.testRequirements.playwright[0] // empty')"
  if [[ -n "$spec" && -e "$REPO_ROOT/$spec" ]]; then
    echo "$spec"
    return 0
  fi

  spec="$(playwright_output_path_for_slice "$slice_id")"
  if [[ -e "$REPO_ROOT/$spec" ]]; then
    echo "$spec"
    return 0
  fi

  if [[ -f "$PLAYWRIGHT_REGRESSION_INDEX" ]]; then
    spec="$(jq -r --arg id "$slice_id" '.slices[$id].specPath // empty' "$PLAYWRIGHT_REGRESSION_INDEX")"
    if [[ -n "$spec" && -e "$REPO_ROOT/$spec" ]]; then
      echo "$spec"
      return 0
    fi
  fi
  return 1
}

should_run_full_playwright_suite() {
  local slice_id="${1:-}"
  local scope every_n counter_file count
  scope="$(playwright_scope_for_checks)"
  if [[ "$scope" == "full" || -z "$slice_id" ]]; then
    return 0
  fi
  every_n="$(playwright_full_every_n)"
  if [[ "$every_n" -le 0 ]]; then
    return 1
  fi
  counter_file="${HARNESS_ROOT}/generated/playwright-full-counter.json"
  mkdir -p "$(dirname "$counter_file")"
  if [[ ! -f "$counter_file" ]]; then
    echo '{"passCount":0}' >"$counter_file"
  fi
  count="$(jq -r '.passCount // 0' "$counter_file")"
  if (( count > 0 && count % every_n == 0 )); then
    return 0
  fi
  return 1
}

slice_completion_artifact_paths() {
  local slice_json="$1"
  echo "$slice_json" | jq -r '(.completionArtifacts // [])[]?'
}

expand_scope_allowlist_lockfiles() {
  local -a allowlist=("$@")
  local entry
  local -a expanded=("${allowlist[@]}")
  for entry in "${allowlist[@]}"; do
    [[ -z "$entry" ]] && continue
    if [[ "$entry" == */package.json || "$entry" == package.json ]]; then
      expanded+=("package-lock.json")
    fi
  done
  if [[ ${#expanded[@]} -eq 0 ]]; then
    return 0
  fi
  printf '%s\n' "${expanded[@]}" | sort -u
}

build_slice_scope_allowlist() {
  local slice_id="$1"
  local slice_json agent_type
  slice_json="$(get_slice_json "$slice_id")"
  [[ -z "$slice_json" || "$slice_json" == "null" ]] && return 1

  agent_type="$(echo "$slice_json" | jq -r '.agent // "backend"')"
  local -a allowlist=()
  local artifact path layer

  while IFS= read -r artifact; do
    [[ -z "$artifact" ]] && continue
    allowlist+=("$artifact")
  done < <(slice_completion_artifact_paths "$slice_json")

  for layer in unit integration component playwright; do
    while IFS= read -r path; do
      [[ -z "$path" ]] && continue
      allowlist+=("$path")
    done < <(echo "$slice_json" | jq -r --arg layer "$layer" '.testRequirements[$layer][]?')
  done

  allowlist+=("ai-harness/generated/runs/screenshots/${slice_id}")
  allowlist+=("ai-harness/state/progress.md")
  allowlist+=("ai-harness/state/guardrails.md")
  allowlist+=("ai-harness/whole-app-backlog.json")

  if [[ "$agent_type" == "frontend" ]]; then
    while IFS= read -r path; do
      [[ -z "$path" ]] && continue
      allowlist+=("$path")
    done < <(jq -r '.computationalChecks.scopeAllowlist[]?' "$LOOP_CONFIG")
  fi

  expand_scope_allowlist_lockfiles "${allowlist[@]}"
}

path_in_scope_allowlist() {
  local file_path="$1"
  shift
  local entry
  for entry in "$@"; do
    [[ -z "$entry" ]] && continue
    if [[ "$file_path" == "$entry" || "$file_path" == "${entry}/"* ]]; then
      return 0
    fi
  done
  return 1
}

playwright_spec_rel_path_for_slice() {
  local slice_id="$1"
  echo "tests/playwright-ui/scenarios/${slice_id}.spec.ts"
}

# Paths written by the browser-test gate after implementer scope already passed.
browser_test_owned_paths() {
  local slice_id="$1"
  local run_id="${2:-}"
  printf '%s\n' \
    "ai-harness/playwright-regression-index.json" \
    "$(playwright_spec_rel_path_for_slice "$slice_id")"
  if [[ -n "$run_id" ]]; then
    printf '%s\n' "ai-harness/generated/runs/ux-bugs/${slice_id}/${run_id}.json"
  fi
  printf '%s\n' "ai-harness/generated/runs/screenshots/${slice_id}/browser-test"
}

path_is_browser_test_owned() {
  local slice_id="$1"
  local file_path="$2"
  local owned_path
  while IFS= read -r owned_path; do
    [[ -z "$owned_path" ]] && continue
    if [[ "$file_path" == "$owned_path" || "$file_path" == "${owned_path}/"* ]]; then
      return 0
    fi
  done < <(browser_test_owned_paths "$slice_id")
  return 1
}

revert_slice_workspace_changes() {
  local slice_id="$1"
  if ! git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    return 0
  fi

  local -a allowlist=() restore_paths=() clean_paths=()
  local file_path entry

  while IFS= read -r entry; do
    [[ -z "$entry" ]] && continue
    allowlist+=("$entry")
  done < <(build_slice_scope_allowlist "$slice_id")

  while IFS= read -r file_path; do
    [[ -z "$file_path" ]] && continue
    if path_is_browser_test_owned "$slice_id" "$file_path"; then
      continue
    fi
    if path_in_scope_allowlist "$file_path" "${allowlist[@]}"; then
      restore_paths+=("$file_path")
    fi
  done < <(git -C "$REPO_ROOT" diff --name-only HEAD 2>/dev/null || true)

  while IFS= read -r file_path; do
    [[ -z "$file_path" ]] && continue
    if path_is_browser_test_owned "$slice_id" "$file_path"; then
      continue
    fi
    if path_in_scope_allowlist "$file_path" "${allowlist[@]}"; then
      clean_paths+=("$file_path")
    fi
  done < <(git -C "$REPO_ROOT" ls-files --others --exclude-standard 2>/dev/null || true)

  if [[ ${#restore_paths[@]} -gt 0 ]]; then
    git -C "$REPO_ROOT" restore -- "${restore_paths[@]}" 2>/dev/null || true
  fi

  for file_path in "${clean_paths[@]}"; do
    if [[ -d "$REPO_ROOT/$file_path" ]]; then
      rm -rf "$REPO_ROOT/$file_path"
    elif [[ -f "$REPO_ROOT/$file_path" ]]; then
      rm -f "$REPO_ROOT/$file_path"
    fi
  done

  if [[ ${#restore_paths[@]} -gt 0 || ${#clean_paths[@]} -gt 0 ]]; then
    aih_warn "Reverted in-scope workspace changes for slice ${slice_id} (${#restore_paths[@]} tracked, ${#clean_paths[@]} untracked)"
  fi
}

parse_slice_defer_from_agent() {
  local agent_text="$1"
  local line target reason
  line="$(echo "$agent_text" | grep -E '^SLICE_DEFER ' | tail -1 || true)"
  [[ -n "$line" ]] || return 1
  target="$(echo "$line" | sed -E 's/^SLICE_DEFER ([^ ]+).*/\1/')"
  reason="$(echo "$line" | sed -E 's/^SLICE_DEFER [^ ]+ //')"
  [[ -n "$target" && -n "$reason" ]] || return 1
  printf '%s\t%s' "$target" "$reason"
}

handle_slice_defer() {
  local current_slice="$1"
  local target_slice="$2"
  local reason="$3"
  local set_by="${4:-implementer}"

  if ! slice_json="$(get_slice_json "$target_slice")" || [[ -z "$slice_json" || "$slice_json" == "null" ]]; then
    aih_err "SLICE_DEFER target not found in backlog: ${target_slice}"
    return 1
  fi

  revert_slice_workspace_changes "$current_slice"
  mark_slice_reopened "$target_slice" "$reason" "$set_by" "deferred" "$current_slice"
  append_slice_history "$current_slice" "deferred" "$reason" "harness" "$target_slice"
  set_loop_slice_override "$target_slice" "$reason" "ralph-once"
  append_guardrail "$current_slice" "Deferred to slice ${target_slice}: ${reason}"
  append_progress "$current_slice" "deferred_to:${target_slice}"
  aih_warn "Slice ${current_slice} deferred — next iteration will focus ${target_slice}"
  return 0
}

detect_out_of_slice_owner_from_checks() {
  local current_slice="$1"
  local run_id="$2"
  local excerpt owner path paths_json
  excerpt="$(summarize_checks_failure_excerpts "$run_id" 2>/dev/null || true)"
  [[ -n "$excerpt" ]] || return 1

  paths_json="$(node -e "
    const m = require('${CHECK_LOG_EXCERPT_JS}');
    const text = process.argv[1];
    console.log(JSON.stringify(m.extractFailingTestPaths(text)));
  " "$excerpt" 2>/dev/null || echo '[]')"
  [[ "$paths_json" != "[]" ]] || return 1

  local -a owners=()
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    owner="$(slice_owning_test_path "$path" 2>/dev/null || true)"
    if [[ -n "$owner" && "$owner" != "$current_slice" ]]; then
      if [[ " ${owners[*]} " != *" ${owner} "* ]]; then
        owners+=("$owner")
      fi
    fi
  done < <(echo "$paths_json" | jq -r '.[]?' | sort -u)

  if [[ ${#owners[@]} -eq 1 ]]; then
    echo "${owners[0]}"
    return 0
  fi
  return 1
}

loop_auto_defer_out_of_slice_enabled() {
  jq -r '.loop.autoDeferOutOfSliceCheckFailures // false' "$LOOP_CONFIG"
}

check_slice_scope_violations() {
  local slice_id="$1"
  local exclude_browser_owned="${2:-false}"
  local slice_json exclude_id artifact file_path
  slice_json="$(get_slice_json "$slice_id")"
  [[ -z "$slice_json" || "$slice_json" == "null" ]] && return 1

  local -a allowlist=()
  while IFS= read -r file_path; do
    [[ -z "$file_path" ]] && continue
    allowlist+=("$file_path")
  done < <(build_slice_scope_allowlist "$slice_id")

  local -a violations=()
  while IFS= read -r file_path; do
    [[ -z "$file_path" ]] && continue
    if [[ "$exclude_browser_owned" == "true" ]] && path_is_browser_test_owned "$slice_id" "$file_path"; then
      continue
    fi
    if ! path_in_scope_allowlist "$file_path" "${allowlist[@]}"; then
      violations+=("$file_path")
    fi
  done < <(git_changed_files)

  while IFS= read -r exclude_id; do
    [[ -z "$exclude_id" ]] && continue
    while IFS= read -r artifact; do
      [[ -z "$artifact" ]] && continue
      while IFS= read -r file_path; do
        [[ -z "$file_path" ]] && continue
        if [[ "$file_path" == "$artifact" || "$file_path" == "${artifact}/"* ]]; then
          violations+=("$file_path")
        fi
      done < <(git_changed_files)
    done < <(get_slice_json "$exclude_id" | jq -r '.completionArtifacts[]?')
  done < <(echo "$slice_json" | jq -r '.excludes[]?')

  if [[ ${#violations[@]} -eq 0 ]]; then
    return 0
  fi
  printf '%s\n' "$(printf '%s\n' "${violations[@]}" | sort -u)"
  return 1
}

format_ui_screens_to_verify_block() {
  local slice_id="$1"
  local slice_json
  slice_json="$(get_slice_json "$slice_id")"
  [[ -z "$slice_json" || "$slice_json" == "null" ]] && return 0

  local agent_type
  agent_type="$(echo "$slice_json" | jq -r '.agent // "backend"')"
  [[ "$agent_type" != "frontend" && "$agent_type" != "test" ]] && return 0

  local desc keywords
  desc="$(echo "$slice_json" | jq -r '.description // ""' | tr '[:upper:]' '[:lower:]')"
  local -a states=()
  if echo "$desc" | grep -qE 'list|table|collection'; then
    states+=("list default")
    states+=("list with filters/search applied")
    states+=("empty state")
  fi
  if echo "$desc" | grep -qE 'form|create|edit|import'; then
    states+=("create form")
    states+=("edit form")
    states+=("inline field error / validation state")
  fi
  if echo "$desc" | grep -qE 'forbidden|denied|role'; then
    states+=("forbidden / denied state")
  fi
  if echo "$desc" | grep -qE 'modal|dialog|drawer'; then
    states+=("modal open")
  fi

  local artifact route state
  cat <<EOF
## UI screens/states to verify (screenshot each)

EOF
  while IFS= read -r artifact; do
    [[ -z "$artifact" ]] && continue
    if [[ "$artifact" == apps/web/src/app/* ]]; then
      route="$(echo "$artifact" | sed -E 's#apps/web/src/app/##; s#/page\.tsx$##; s#\(.*\)##g; s#\[([^\]]+)\]#:\1#g')"
      route="/${route}"
      route="$(echo "$route" | sed 's#//\+#/#g; s#/$##')"
      [[ "$route" == "/" ]] || route="${route}"
      if [[ ${#states[@]} -eq 0 ]]; then
        printf -- '- %s — default (desktop + mobile where applicable)\n' "$route"
      else
        for state in "${states[@]}"; do
          printf -- '- %s — %s\n' "$route" "$state"
        done
      fi
    fi
  done < <(echo "$slice_json" | jq -r '.completionArtifacts[]?')

  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    artifact="$(test_case_artifact_abs "$ref")"
    [[ -f "$artifact" ]] || continue
    while IFS= read -r state; do
      [[ -z "$state" ]] && continue
      printf -- '- %s\n' "$state"
    done < <(jq -r '.cases[]? | select(.layer == "browser") | "- \(.title // .id) — browser case"' "$artifact")
  done < <(slice_requirement_tag_refs "$slice_id")
}

load_test_cases_json_for_slice() {
  local slice_id="$1"
  local refs merged="[]"
  refs="$(jq -r --arg id "$slice_id" '.slices[] | select(.id == $id) | .acceptance[]?' "$BACKLOG")"
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    local artifact cases
    artifact="$(test_case_artifact_abs "$ref")"
    [[ -f "$artifact" ]] || continue
    cases="$(jq -c '.cases // []' "$artifact")"
    merged="$(jq -c --argjson c "$cases" '. + $c' <<< "$merged")"
  done <<< "$refs"
  jq -n --arg slice "$slice_id" --argjson cases "$merged" \
    '{sliceId: $slice, requirementTags: [], cases: $cases}'
}

slice_requirement_tag_refs() {
  local slice_id="$1"
  jq -r --arg id "$slice_id" '.slices[] | select(.id == $id) | .acceptance[]?' "$BACKLOG"
}

# Back-compat aliases
slice_product_item_refs() { slice_requirement_tag_refs "$@"; }
product_item_test_cases_current() { requirement_tag_test_cases_current "$@"; }
pick_next_testgen_product_item_id() { pick_next_testgen_requirement_tag; }
reset_product_item_on_doc_drift() { reset_requirement_tag_on_doc_drift "$@"; }

# Testgen agent: writes test case artifacts only (no Playwright MCP).
agent_invoke_testgen() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args fmt
  args=(-p --force --trust --model "$model")
  read -ra fmt <<< "$(agent_output_format_args)"
  args+=("${fmt[@]}")
  local timeout_ms idle_config
  idle_config="$TESTGEN_CONFIG"
  timeout_ms="$(get_agent_timeout_ms "$idle_config")"
  AIH_HARNESS_CONFIG="$idle_config" run_agent_with_timeout_ms "$timeout_ms" "$outfile" "$AGENT_BIN" "${args[@]}" "$prompt"
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

write_slice_scope_report() {
  local run_id="$1"
  local slice_id="$2"
  local pass_flag="$3"
  shift 3
  local violations_json="[]"
  if [[ $# -gt 0 ]]; then
    violations_json="$(printf '%s\n' "$@" | jq -R . | jq -s .)"
  fi
  local report
  report="$(jq -n \
    --arg slice "$slice_id" \
    --argjson pass "$pass_flag" \
    --argjson violations "$violations_json" \
    '{slice: $slice, pass: $pass, violations: $violations}')"
  write_run_report "${run_id}-scope.json" "$report"
}

slice_uses_browser_mcp() {
  local slice_id="${1:-}"
  slice_requires_web_runtime "$slice_id" || [[ "${AIH_BROWSER_MCP:-}" == "1" ]]
}

slice_requires_browser_test() {
  local slice_id="${1:-}"
  [[ -n "$slice_id" ]] || return 1
  local agent
  agent="$(get_slice_field "$slice_id" agent)"
  jq -e --arg agent "$agent" '.browserTest.activeWhenAgent[]? | select(. == $agent)' "$LOOP_CONFIG" >/dev/null 2>&1
}

playwright_mcp_artifact_dirs() {
  printf '%s\n' "$PLAYWRIGHT_MCP_LEGACY_DIR" "$PLAYWRIGHT_MCP_OUTPUT_DIR"
}

generated_retention_minutes() {
  if [[ -n "${AIH_GENERATED_RETENTION_MINUTES:-}" ]]; then
    echo "${AIH_GENERATED_RETENTION_MINUTES}"
    return 0
  fi
  jq -r '.loop.generatedRetentionMinutes // 60' "$LOOP_CONFIG"
}

generated_cleanup_protected_basename() {
  local base="$1"
  case "$base" in
    loop.pid|loop.log|preview-stack.pids|preview-aux.pids|preview-stack.mode|preview-supervisor.stop|preview-web.refresh|preview-combined.log|preview-stack.log|preview-api.log|preview-web.log|preview-db.log)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

cleanup_generated_dir_by_age() {
  local dir="$1"
  local retention_min="$2"
  [[ -d "$dir" ]] || return 0

  local count=0 f
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    rm -f "$f"
    count=$((count + 1))
  done < <(find "$dir" -type f -mmin "+${retention_min}" 2>/dev/null || true)

  find "$dir" -depth -type d -empty -delete 2>/dev/null || true
  echo "$count"
}

cleanup_generated_artifacts() {
  if [[ "${AIH_SKIP_GENERATED_CLEANUP:-}" == "1" ]]; then
    return 0
  fi

  local retention_min removed=0 count base f
  retention_min="$(generated_retention_minutes)"
  if [[ ! "$retention_min" =~ ^[0-9]+$ ]] || [[ "$retention_min" -le 0 ]]; then
    return 0
  fi

  ensure_runs_dir

  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    base="$(basename "$f")"
    if generated_cleanup_protected_basename "$base"; then
      continue
    fi
    rm -f "$f"
    removed=$((removed + 1))
  done < <(find "$RUNS_DIR" -maxdepth 1 -type f -mmin "+${retention_min}" 2>/dev/null || true)

  for dir in "$SCREENSHOTS_ROOT" "$UX_BUGS_ROOT" "$PLAYWRIGHT_MCP_OUTPUT_DIR"; do
    if [[ -d "$dir" ]]; then
      count="$(cleanup_generated_dir_by_age "$dir" "$retention_min")"
      removed=$((removed + count))
    fi
  done

  if [[ "$removed" -gt 0 ]]; then
    echo "==> Generated artifacts cleaned (retention=${retention_min}m, removed=${removed})"
  fi
}

cleanup_playwright_mcp_dir() {
  local dir="$1"
  local keep="${2:-0}"
  [[ -d "$dir" ]] || return 0

  if [[ "$keep" -le 0 ]]; then
    find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
    return 0
  fi

  local f
  for f in $(ls -t "$dir" 2>/dev/null | tail -n +$((keep + 1))); do
    rm -f "${dir}/${f}"
  done
}

cleanup_playwright_mcp_artifacts() {
  if [[ "${AIH_SKIP_PLAYWRIGHT_MCP_CLEANUP:-}" == "1" ]]; then
    return 0
  fi

  local keep="${AIH_PLAYWRIGHT_MCP_KEEP:-0}"
  local dir removed=0
  ensure_runs_dir
  while IFS= read -r dir; do
    if [[ -d "$dir" ]] && [[ -n "$(ls -A "$dir" 2>/dev/null || true)" ]]; then
      cleanup_playwright_mcp_dir "$dir" "$keep"
      removed=1
    fi
  done < <(playwright_mcp_artifact_dirs)

  if [[ "$removed" -eq 1 ]]; then
    echo "==> Playwright MCP artifacts cleaned (keep=${keep})"
  fi
}

agent_invoke() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  local slice_id="${4:-${AIH_CHECK_SLICE:-}}"
  require_agent
  local -a args fmt
  args=(-p --force --model "$model")
  read -ra fmt <<< "$(agent_output_format_args)"
  args+=("${fmt[@]}")
  if slice_uses_browser_mcp "$slice_id"; then
    args+=(--approve-mcps)
  fi
  local timeout_ms idle_config
  idle_config="$LOOP_CONFIG"
  timeout_ms="$(get_agent_timeout_ms "$idle_config")"
  AIH_HARNESS_CONFIG="$idle_config" run_agent_with_timeout_ms "$timeout_ms" "$outfile" "$AGENT_BIN" "${args[@]}" "$prompt"
}

# Read-only reviewer: plan mode blocks edits; prompt forbids shell/tests.
agent_invoke_review() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args fmt
  args=(-p --force --trust --model "$model" --mode plan)
  read -ra fmt <<< "$(agent_output_format_args)"
  args+=("${fmt[@]}")
  local timeout_ms idle_config
  idle_config="$LOOP_CONFIG"
  timeout_ms="$(get_agent_timeout_ms "$idle_config")"
  AIH_HARNESS_CONFIG="$idle_config" run_agent_with_timeout_ms "$timeout_ms" "$outfile" "$AGENT_BIN" "${args[@]}" "$prompt"
}

# Browser tester: Playwright MCP enabled; prompt forbids file edits.
agent_invoke_browser_test() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args fmt
  args=(-p --force --trust --approve-mcps --model "$model")
  read -ra fmt <<< "$(agent_output_format_args)"
  args+=("${fmt[@]}")
  local timeout_ms idle_config
  idle_config="$LOOP_CONFIG"
  timeout_ms="$(get_agent_timeout_ms "$idle_config")"
  AIH_HARNESS_CONFIG="$idle_config" run_agent_with_timeout_ms "$timeout_ms" "$outfile" "$AGENT_BIN" "${args[@]}" "$prompt"
}

git_changed_files() {
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    return 0
  fi
  local git_root repo_prefix path normalized
  git_root="$(git rev-parse --show-toplevel 2>/dev/null || echo "$REPO_ROOT")"
  repo_prefix="${REPO_ROOT#"${git_root}/"}"
  if [[ "$repo_prefix" == "$REPO_ROOT" ]]; then
    repo_prefix=""
  fi
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    normalized="$path"
    if [[ -n "$repo_prefix" ]]; then
      if [[ "$path" == "${repo_prefix}/"* ]]; then
        normalized="${path#${repo_prefix}/}"
      else
        continue
      fi
    fi
    printf '%s\n' "$normalized"
  done < <({
    git diff --name-only HEAD 2>/dev/null || true
    git diff --cached --name-only 2>/dev/null || true
    git ls-files --others --exclude-standard 2>/dev/null || true
  } | sed '/^$/d' | sort -u)
}

git_path_has_changes() {
  local rel="$1"
  [[ -n "$rel" ]] || return 1
  if [[ -e "$REPO_ROOT/$rel" ]] && ! git ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
    return 0
  fi
  ! git diff --quiet -- "$rel" 2>/dev/null && return 0
  ! git diff --cached --quiet -- "$rel" 2>/dev/null && return 0
  return 1
}

git_commit_allowlisted_paths() {
  local message="$1"
  shift
  local paths=("$@")
  [[ ${#paths[@]} -gt 0 ]] || return 0
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    return 0
  fi

  local to_add=()
  local rel
  for rel in "${paths[@]}"; do
    [[ -n "$rel" ]] || continue
    [[ -e "$REPO_ROOT/$rel" ]] || continue
    if git_path_has_changes "$rel"; then
      to_add+=("$rel")
    fi
  done

  [[ ${#to_add[@]} -gt 0 ]] || return 0
  git add -- "${to_add[@]}"
  git commit -m "$message" --no-verify 2>/dev/null || true
}

testgen_owned_paths() {
  local requirement_tag="$1"
  printf '%s\n' \
    "$(test_case_artifact_path "$requirement_tag")" \
    "ai-harness/test-case-index.json" \
    "ai-harness/whole-app-backlog.json" \
    "ai-harness/state/progress.md"
}

git_commit_testgen_pass() {
  local requirement_tag="$1"
  local -a paths=()
  local path
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    paths+=("$path")
  done < <(testgen_owned_paths "$requirement_tag")
  git_commit_allowlisted_paths "aih: generate test cases for ${requirement_tag}" "${paths[@]}"
}

git_commit_browser_test_pass() {
  local slice_id="$1"
  local run_id="$2"
  local -a paths=()
  local path
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    paths+=("$path")
  done < <(browser_test_owned_paths "$slice_id" "$run_id")
  git_commit_allowlisted_paths "aih: browser test regression for ${slice_id}" "${paths[@]}"
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

find_browser_test_report_for_slice() {
  local slice_id="$1"
  local run_id="${2:-}"
  if [[ -n "$run_id" && -f "${RUNS_DIR}/${run_id}-browser-test.json" ]]; then
    cat "${RUNS_DIR}/${run_id}-browser-test.json"
    return 0
  fi
  local f
  for f in $(ls -t "${RUNS_DIR}"/*-browser-test.json 2>/dev/null || true); do
    if jq -e --arg s "$slice_id" '.slice == $s and (.pass == true or .skipped == true)' "$f" >/dev/null 2>&1; then
      cat "$f"
      return 0
    fi
  done
  echo '{"pass":false,"skipped":false,"note":"no browser test report found for slice"}'
}

find_latest_failed_run_id_for_slice() {
  local slice_id="$1"
  local artifact_kind="$2"
  local f
  for f in $(ls -t "${RUNS_DIR}"/*-"${artifact_kind}".json 2>/dev/null || true); do
    if jq -e --arg s "$slice_id" '.slice == $s and .pass == false' "$f" >/dev/null 2>&1; then
      if [[ "$artifact_kind" == "browser-test" ]]; then
        jq -e --arg s "$slice_id" '.slice == $s and .pass == false and (.skipped // false) == false' "$f" >/dev/null 2>&1 || continue
      fi
      basename "$f" "-${artifact_kind}.json"
      return 0
    fi
  done
  return 1
}

summarize_checks_failures() {
  local run_id="$1"
  local max_chars="${2:-32000}"
  local json_file="${RUNS_DIR}/${run_id}-checks.json"
  [[ -f "$json_file" ]] || return 1
  jq -e '.pass == false and ((.failures // []) | length) > 0' "$json_file" >/dev/null 2>&1 || return 1
  jq '{slice, timestamp, failureCount: (.failures | length), failures}' "$json_file" 2>/dev/null | head -c "$max_chars"
}

# Markdown excerpts from per-script check logs — injected into implementer prompts.
summarize_checks_failure_excerpts() {
  local run_id="$1"
  local max_chars="${2:-8000}"
  local json_file="${RUNS_DIR}/${run_id}-checks.json"
  local slice_id failures_json section=""
  [[ -f "$json_file" ]] || return 1
  slice_id="$(jq -r '.slice // empty' "$json_file")"
  failures_json="$(jq -c '.failures // []' "$json_file")"
  [[ "$failures_json" != "[]" ]] || return 1

  local entry log_file script excerpt scope_hint log_base
  while IFS= read -r entry; do
    [[ -z "$entry" ]] && continue
    log_file="$(echo "$entry" | jq -r '.logExcerpt as $e | if ($e // "") != "" then empty else .logFile // empty end')"
    script="$(echo "$entry" | jq -r '.script // "check"')"
    excerpt="$(echo "$entry" | jq -r '.logExcerpt // empty')"
    scope_hint="$(echo "$entry" | jq -r '.scopeHint // empty')"

    if [[ -z "$excerpt" && -n "$log_file" && -f "$log_file" ]]; then
      excerpt="$(extract_check_log_failure_excerpt "$log_file" "$max_chars")"
      if [[ -n "$excerpt" && -n "$slice_id" ]]; then
        scope_hint="$(format_out_of_slice_test_hint "$slice_id" "$excerpt")"
      fi
    fi
    [[ -n "$excerpt" ]] || continue

    log_base="$(basename "$log_file")"
    [[ -n "$log_base" ]] || log_base="${run_id}-check-${script//[:]/-}.log"

    section="${section}#### ${script} log excerpt (\`${log_base}\`)

"
    if [[ -n "$scope_hint" ]]; then
      section="${section}${scope_hint}
"
    fi
    section="${section}\`\`\`text
${excerpt}
\`\`\`

"
  done < <(echo "$failures_json" | jq -c '.[]')

  [[ -n "$section" ]] || return 1
  printf '%s' "${section}"
}

# Short one-liner for guardrails.md when computational checks fail.
summarize_checks_guardrail_line() {
  local run_id="$1"
  local json_file="${RUNS_DIR}/${run_id}-checks.json"
  local slice_id line=""
  [[ -f "$json_file" ]] || return 1
  slice_id="$(jq -r '.slice // empty' "$json_file")"

  local entry script msg excerpt case_id
  entry="$(jq -c '.failures[0] // empty' "$json_file")"
  [[ -n "$entry" && "$entry" != "null" ]] || return 1

  script="$(echo "$entry" | jq -r '.script // empty')"
  msg="$(echo "$entry" | jq -r '.message // empty')"
  excerpt="$(echo "$entry" | jq -r '.logExcerpt // empty')"
  if [[ -z "$excerpt" ]]; then
    local log_file
    log_file="$(echo "$entry" | jq -r '.logFile // empty')"
    if [[ -n "$log_file" && -f "$log_file" ]]; then
      excerpt="$(extract_check_log_failure_excerpt "$log_file" 2000)"
    fi
  fi

  if [[ -n "$script" ]]; then
    line="npm run ${script} failed"
    case_id="$(node -e "
      const m = require('${CHECK_LOG_EXCERPT_JS}');
      const ids = m.extractFailingCaseIds(process.argv[1]);
      if (ids.length) process.stdout.write(ids[0]);
    " "$excerpt" 2>/dev/null || true)"
    if [[ -n "$case_id" ]]; then
      line="${line} — ${case_id}"
    elif [[ -n "$excerpt" ]]; then
      local test_name
      test_name="$(echo "$excerpt" | grep -E '^✖ ' | head -1 | sed 's/^✖ //' || true)"
      [[ -n "$test_name" ]] && line="${line} — ${test_name}"
    fi
  elif [[ -n "$msg" ]]; then
    line="$msg"
  else
    line="see ${run_id}-checks.json"
  fi

  local scope_hint
  if [[ -n "$excerpt" && -n "$slice_id" ]]; then
    scope_hint="$(format_out_of_slice_test_hint "$slice_id" "$excerpt" | head -1 || true)"
    if echo "$scope_hint" | grep -q 'owned by slice'; then
      line="${line}; $(echo "$scope_hint" | sed 's/^- //')"
    fi
  fi

  printf '%s' "$line"
}

summarize_browser_test_failures() {
  local run_id="$1"
  local max_chars="${2:-12000}"
  local text_file="${RUNS_DIR}/${run_id}-browser-test.txt"
  local line block=""
  [[ -f "$text_file" ]] || return 1
  while IFS= read -r line; do
    if echo "$line" | grep -qE ': FAIL|BROWSER_TEST_FAIL|^\*\*cases:|^UX-[a-z0-9-]+-[0-9]{3}:[[:space:]]*P[01]'; then
      block+="${line}"$'\n'
    fi
  done < "$text_file"
  [[ -n "$block" ]] || return 1
  printf '%s' "$block" | head -c "$max_chars"
}

browser_test_retry_failed_cases_first() {
  jq -r '.browserTest.retryFailedCasesFirst // true' "$LOOP_CONFIG"
}

extract_failed_browser_case_ids() {
  local run_id="$1"
  local text_file="${RUNS_DIR}/${run_id}-browser-test.txt"
  [[ -f "$text_file" ]] || return 1
  grep -oE 'TC-[A-Z0-9][A-Z0-9-]*:[[:space:]]*FAIL' "$text_file" 2>/dev/null \
    | sed -E 's/:[[:space:]]*FAIL$//' \
    | sort -u
}

filter_browser_cases_prompt_block() {
  local slice_id="$1"
  shift
  local ids_json
  [[ $# -gt 0 ]] || return 1
  ids_json="$(printf '%s\n' "$@" | jq -R . | jq -s .)"
  load_test_cases_json_for_slice "$slice_id" | jq -r --argjson ids "$ids_json" '
    .cases[]?
    | select(.layer == "browser")
    | select(.id as $id | $ids | index($id))
    | "- **\(.id)** [\(.category)/\(.priority)]: \(.title)"
      + (if .harnessSkip then "\n  **Harness scope: SKIP \(.harnessSkip)** — do not mark FAIL; report SKIP with this reason tag" else "" end)
      + "\n  Product: \(.traceability | join(", "))\n  Preconditions: \(.preconditions | join("; "))\n  Steps: \(.steps | join(" → "))\n  Expected: \(.expected)"
  ' 2>/dev/null
}

browser_case_ids_still_failing_in_output() {
  local text_file="$1"
  shift
  local case_id
  [[ -f "$text_file" ]] || return 1
  for case_id in "$@"; do
    if grep -qE "${case_id}:[[:space:]]*FAIL" "$text_file" 2>/dev/null; then
      return 1
    fi
  done
  return 0
}

extract_skipped_browser_case_ids() {
  local text_file="$1"
  [[ -f "$text_file" ]] || return 1
  grep -oE 'TC-[A-Z0-9][A-Z0-9-]*:[[:space:]]*SKIP' "$text_file" 2>/dev/null \
    | sed -E 's/:[[:space:]]*SKIP$//' \
    | sort -u
}

summarize_review_failures() {
  local run_id="$1"
  local max_chars="${2:-12000}"
  local text_file="${RUNS_DIR}/${run_id}-review.txt"
  local block=""
  [[ -f "$text_file" ]] || return 1
  block="$(awk '
    /\*\*Blocker|### Blocker|## Blocker/ { capture=1 }
    capture { print }
  ' "$text_file")"
  if [[ -z "$block" ]]; then
    block="$(grep -E 'REVIEW_FAIL|Blocker|blocker|\bgap\b|missing|out of scope|not met|violat' -i "$text_file" 2>/dev/null || true)"
  fi
  [[ -n "$block" ]] || return 1
  printf '%s' "$block" | head -c "$max_chars"
}

summarize_scope_failures() {
  local run_id="$1"
  local max_chars="${2:-32000}"
  local json_file="${RUNS_DIR}/${run_id}-scope.json"
  [[ -f "$json_file" ]] || return 1
  jq -e '.pass == false and ((.violations // []) | length) > 0' "$json_file" >/dev/null 2>&1 || return 1
  jq '{slice, violations, hint: "Revert out-of-scope edits or add paths to completionArtifacts / testRequirements in whole-app-backlog.json (see guardrails.md)."}' \
    "$json_file" 2>/dev/null | head -c "$max_chars"
}

build_implementer_prior_gate_feedback() {
  local slice_id="$1"
  local block sections="" excerpt_block=""
  local scope_run="" checks_run="" browser_run="" review_run=""

  if scope_run="$(find_latest_failed_run_id_for_slice "$slice_id" scope)"; then
    block="$(summarize_scope_failures "$scope_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      sections="${sections}### Scope gate failures (\`${scope_run}\`)

Fix every out-of-scope path below before signaling \`SLICE_DONE\`. Run \`npm run aih:scope -- ${slice_id}\` to verify locally.

\`\`\`json
${block}
\`\`\`

"
    fi
  fi

  if checks_run="$(find_latest_failed_run_id_for_slice "$slice_id" checks)"; then
    block="$(summarize_checks_failures "$checks_run" 2>/dev/null || true)"
    excerpt_block="$(summarize_checks_failure_excerpts "$checks_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      sections="${sections}### Computational checks failures (\`${checks_run}\`)

Fix every item below before signaling \`SLICE_DONE\`. **Read the log excerpts** — they contain assertion errors and test case ids the JSON summary omits.

\`\`\`json
${block}
\`\`\`

"
      if [[ -n "$excerpt_block" ]]; then
        sections="${sections}${excerpt_block}"
      else
        sections="${sections}_(No log excerpts found — open \`ai-harness/generated/runs/${checks_run}-check-*.log\` from \`failures[].logFile\`.)_

"
      fi
    fi
  fi

  if browser_run="$(find_latest_failed_run_id_for_slice "$slice_id" browser-test)"; then
    block="$(summarize_browser_test_failures "$browser_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      sections="${sections}### Browser test failures (\`${browser_run}\`)

Fix only the failed cases below before signaling \`SLICE_DONE\`.

\`\`\`
${block}
\`\`\`

"
    fi
  fi

  if review_run="$(find_latest_failed_run_id_for_slice "$slice_id" review)"; then
    block="$(summarize_review_failures "$review_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      sections="${sections}### AI code review blockers (\`${review_run}\`)

Resolve the blockers below before signaling \`SLICE_DONE\`.

\`\`\`
${block}
\`\`\`

"
    fi
  fi

  [[ -n "$sections" ]] || return 0

  cat <<EOF
## Prior gate failures — address these first

This slice failed harness gates on a previous iteration. Only failure summaries are included below — fix them before signaling \`SLICE_DONE\`.

${sections}
EOF
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

preview_stack_reachable() {
  local api_port="$(aih_api_port)"
  local web_port="$(aih_web_port)"
  local body status db code

  body="$(curl --connect-timeout 1 --max-time 2 -sf "http://localhost:${api_port}/api/v1/health" 2>/dev/null || true)"
  status="$(echo "$body" | jq -r '.status // empty' 2>/dev/null || true)"
  db="$(echo "$body" | jq -r '.db // empty' 2>/dev/null || true)"
  [[ "$status" == "ok" && "$db" == "connected" ]] || return 1

  code="$(curl --connect-timeout 1 --max-time 2 -s -o /dev/null -w '%{http_code}' "http://localhost:${web_port}/" 2>/dev/null || true)"
  [[ "$code" == "200" ]]
}

run_preview_stack_script() {
  local preview_script="$1"
  shift
  local log_tmp status

  log_tmp="$(mktemp "${TMPDIR:-/tmp}/aih-preview-cmd.XXXXXX")"
  set +e
  "$preview_script" "$@" >"$log_tmp" 2>&1
  status=$?
  set -e
  cat "$log_tmp"
  rm -f "$log_tmp"
  return "$status"
}

get_preview_verify_gate_timeout_ms() {
  local config="${1:-$LOOP_CONFIG}"
  if [[ -n "${AIH_VERIFY_GATE_TIMEOUT_MS:-}" ]]; then
    echo "$AIH_VERIFY_GATE_TIMEOUT_MS"
    return
  fi
  jq -r ".browserTest.previewVerifyGateTimeoutMs // ${PREVIEW_VERIFY_GATE_DEFAULT_MS}" "$config" 2>/dev/null \
    || echo "$PREVIEW_VERIFY_GATE_DEFAULT_MS"
}

# Browser-test gate: start preview when down; gate-verify when up; restart once if unhealthy.
ensure_preview_stack_for_browser_test() {
  local verify_script="${HARNESS_ROOT}/scripts/verify-stack.sh"
  local preview_script="${HARNESS_ROOT}/scripts/preview-stack.sh"
  local gate_timeout_ms stack_status

  gate_timeout_ms="$(get_preview_verify_gate_timeout_ms)"
  export AIH_VERIFY_GATE_TIMEOUT_MS="$gate_timeout_ms"

  if preview_stack_reachable; then
    echo "==> Preview stack reachable (API + web healthy)"
    return 0
  fi

  if preview_stack_is_running; then
    echo "==> Preview supervisors running but stack not healthy — gate verify (${gate_timeout_ms}ms)"
    set +e
    "$verify_script" --gate 2>&1
    stack_status=$?
    set -e
    if [[ "$stack_status" -eq 0 ]]; then
      return 0
    fi
    echo "==> Preview stack unhealthy — restarting dev preview"
    set +e
    run_preview_stack_script "$preview_script" --down
    stack_status=$?
    set -e
    if [[ "$stack_status" -ne 0 ]]; then
      echo "WARN: preview down returned non-zero (${stack_status}); continuing with start" >&2
    fi
  else
    echo "==> Preview stack not running — starting dev preview"
  fi

  set +e
  run_preview_stack_script "$preview_script" --mode dev
  stack_status=$?
  set -e
  if [[ "$stack_status" -ne 0 ]]; then
    echo "ERROR: failed to start preview stack for browser test" >&2
    return 1
  fi
  if ! preview_stack_reachable; then
    echo "ERROR: preview start finished but API/web are not healthy" >&2
    return 1
  fi
  return 0
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

# Kill preview-supervisor.sh processes left behind by interrupted preview-stack (^C).
stop_stray_preview_supervisors() {
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi

  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    [[ "$pid" == "$$" ]] && continue
    preview_log_stack "stopping stray preview supervisor (pid=${pid})"
    terminate_pid "$pid"
  done < <(pgrep -f 'preview-supervisor\.sh (api|web)' 2>/dev/null || true)
}

# Kill any process listening on preview API/web ports (orphan next dev after ^C).
stop_preview_port_listeners() {
  local api_port="$(aih_api_port)"
  local web_port="$(aih_web_port)"

  if ! command -v lsof >/dev/null 2>&1; then
    preview_log_stack "WARN: lsof unavailable — cannot verify preview ports are free"
    return 0
  fi

  local port port_pid
  for port in "$api_port" "$web_port"; do
    while IFS= read -r port_pid; do
      [[ -z "$port_pid" ]] && continue
      preview_log_stack "stopping listener on port ${port} (pid=${port_pid})"
      terminate_pid "$port_pid"
    done < <(lsof -ti ":${port}" 2>/dev/null || true)
  done
}

wait_for_preview_ports_free() {
  local api_port="$(aih_api_port)"
  local web_port="$(aih_web_port)"

  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi

  local port
  for port in "$api_port" "$web_port"; do
    local _
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      lsof -ti ":${port}" >/dev/null 2>&1 || break
      sleep 0.3
    done
  done
}

# Full dev-preview reset before start: supervisors, orphans, ports, then .next cache.
reset_dev_preview_stack() {
  preview_log_stack "resetting dev preview stack (supervisors, ports, .next)"
  stop_preview_supervisors
  stop_stray_preview_supervisors
  stop_preview_port_listeners
  wait_for_preview_ports_free
  remove_path_safely "$REPO_ROOT/apps/web/.next"
  preview_log_stack "dev preview stack reset complete"
}

# Tear down dev preview processes without clearing .next (used by preview:down).
stop_dev_preview_processes() {
  stop_preview_supervisors
  stop_stray_preview_supervisors
  stop_preview_port_listeners
  wait_for_preview_ports_free
}

start_preview_supervisors() {
  local supervisor_script
  supervisor_script="$(preview_supervisor_script)"
  ensure_runs_dir
  rm -f "$PREVIEW_SUPERVISOR_STOP_FILE" "$PREVIEW_WEB_REFRESH_FILE"
  : > "$PREVIEW_PID_FILE"

  "$supervisor_script" api </dev/null >/dev/null 2>&1 &
  echo $! >> "$PREVIEW_PID_FILE"
  local api_sup=$!
  "$supervisor_script" web </dev/null >/dev/null 2>&1 &
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
  nudge_preview_service_restart "$(aih_api_port)"
}

nudge_preview_web_restart() {
  read_preview_supervisor_pids || return 0
  touch "$PREVIEW_WEB_REFRESH_FILE"
  nudge_preview_service_restart "$(aih_web_port)"
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
    stop_preview_port_listeners
    wait_for_preview_ports_free
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

# After a full workspace build (production .next), stop stray dev servers and clear cache.
refresh_preview_web_after_build() {
  [[ -d "$REPO_ROOT/apps/web" ]] || return 0
  if preview_stack_is_running; then
    return 0
  fi
  stop_preview_web_process
  clean_web_next_cache
}

# Build library packages while preview dev serves api/web (avoids .next and dist churn).
run_build_for_checks() {
  local rel pkg pkg_json
  local -a rel_paths=(packages/domain packages/config apps/api apps/web)

  if preview_stack_is_running; then
    echo "Preview stack running — skipping apps/web and apps/api build to preserve dev runtime"
    for rel in "${rel_paths[@]}"; do
      [[ "$rel" == apps/web || "$rel" == apps/api ]] && continue
      pkg_json="$REPO_ROOT/$rel/package.json"
      [[ -f "$pkg_json" ]] || continue
      pkg="$(jq -r '.name // empty' "$pkg_json")"
      [[ -n "$pkg" ]] || continue
      if jq -e --arg s "build" '.scripts[$s]' "$pkg_json" >/dev/null 2>&1; then
        npm run build --workspace "$pkg" || return 1
      fi
    done
    for pkg_json in "$REPO_ROOT"/packages/*/package.json; do
      [[ -f "$pkg_json" ]] || continue
      rel="${pkg_json#$REPO_ROOT/}"
      rel="${rel%/package.json}"
      [[ "$rel" == packages/domain || "$rel" == packages/config ]] && continue
      pkg="$(jq -r '.name // empty' "$pkg_json")"
      [[ -n "$pkg" ]] || continue
      if jq -e --arg s "build" '.scripts[$s]' "$pkg_json" >/dev/null 2>&1; then
        npm run build --workspace "$pkg" || return 1
      fi
    done
    return 0
  fi

  npm run build || return 1
}

# --- Test compose stack (integration / API e2e; isolated from preview dev DB) ---

test_compose_active_when() {
  jq -r '.computationalChecks.runtimeValidation.testStack.activeWhen // "docker-compose.test.yml"' "$LOOP_CONFIG"
}

test_compose_file() {
  jq -r '.computationalChecks.runtimeValidation.testStack.composeFile // "docker-compose.test.yml"' "$LOOP_CONFIG"
}

test_compose_project() {
  jq -r '.computationalChecks.runtimeValidation.testStack.projectName // "app-test"' "$LOOP_CONFIG"
}

test_stack_configured() {
  local active_when
  active_when="$(test_compose_active_when)"
  [[ -f "$REPO_ROOT/$active_when" ]]
}

check_profile_needs_test_stack() {
  local profile="${1:-$(get_check_profile)}"
  profile_includes_script "$profile" "test:integration" \
    || profile_includes_script "$profile" "test:e2e"
}

test_stack_service_names() {
  jq -r '.computationalChecks.runtimeValidation.testStack.services[]? // "db"' "$LOOP_CONFIG"
}

test_stack_script() {
  echo "${HARNESS_ROOT}/scripts/test-stack.sh"
}

test_db_compose_status() {
  local service="$1"
  "$(test_stack_script)" status "$service" 2>/dev/null || true
}

wait_test_stack_healthy() {
  if ! test_stack_configured; then
    return 0
  fi
  "$(test_stack_script)" wait
}

reset_test_stack_if_needed() {
  if ! test_stack_configured; then
    return 0
  fi
  "$(test_stack_script)" reset
}

script_needs_test_stack() {
  case "${1:-}" in
    test:integration|test:e2e) return 0 ;;
    *) return 1 ;;
  esac
}

# Tear down and recreate the ephemeral test stack, then export connection env vars.
# Called immediately before each integration/e2e npm script so suites do not share DB state.
prepare_test_stack_for_script() {
  local script="${1:-}"
  script_needs_test_stack "$script" || return 0
  if ! test_stack_configured; then
    return 0
  fi
  aih_info "    resetting test stack before ${script} (via $(test_stack_script) reset, AIH_TEST_STACK_RESET=${AIH_TEST_STACK_RESET:-1})"
  if ! reset_test_stack_if_needed; then
    aih_err "test stack reset failed before ${script}"
    return 1
  fi
  export_test_stack_env
  return 0
}

export_test_stack_env() {
  if ! test_stack_configured; then
    return 0
  fi
  local key value
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    value="$(jq -r --arg k "$key" '.computationalChecks.runtimeValidation.testStack.env[$k] // empty' "$LOOP_CONFIG")"
    if [[ -n "$value" && -z "${!key:-}" ]]; then
      export "$key=$value"
    fi
  done < <(jq -r '.computationalChecks.runtimeValidation.testStack.env | keys[]?' "$LOOP_CONFIG" 2>/dev/null || true)
  # Never run integration/e2e against preview dev DB when .env sets DATABASE_URL (5432).
  if [[ -n "${TEST_DATABASE_URL:-}" ]]; then
    export DATABASE_URL="$TEST_DATABASE_URL"
  fi
  if [[ -n "${TEST_REDIS_URL:-}" ]]; then
    export REDIS_URL="$TEST_REDIS_URL"
  fi
  if [[ -n "${TEST_S3_ENDPOINT:-}" ]]; then
    export S3_ENDPOINT="$TEST_S3_ENDPOINT"
  fi
}
