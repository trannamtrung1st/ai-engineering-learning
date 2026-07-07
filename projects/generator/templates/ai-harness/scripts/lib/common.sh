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
  # Preview stack always uses 3007 by default (see README); do not inherit WEB_PORT from .env
  # (often 3000 for manual dev) or verification probes the wrong port.
  echo "${AIH_PREVIEW_WEB_PORT:-3007}"
}

aih_api_port() {
  echo "${AIH_PREVIEW_API_PORT:-${API_PORT:-3001}}"
}

BACKLOG="${HARNESS_ROOT}/whole-app-backlog.json"
TEST_CASE_INDEX="${HARNESS_ROOT}/test-case-index.json"
PLAN_DIR="${HARNESS_ROOT}/plans"
TESTGEN_DOCS_MAP="${HARNESS_ROOT}/config/testgen-docs-map.json"
LOOP_CONFIG="${HARNESS_ROOT}/workflows/ralph-loop.json"
TESTGEN_CONFIG="${HARNESS_ROOT}/workflows/testgen-loop.json"
MANUALS_BACKLOG="${HARNESS_ROOT}/manuals-backlog.json"
MANUALS_INDEX="${HARNESS_ROOT}/manuals-index.json"
MANUALSGEN_DOCS_MAP="${HARNESS_ROOT}/config/manualsgen-docs-map.json"
MANUALSGEN_CONFIG="${HARNESS_ROOT}/workflows/manualsgen-loop.json"
USER_MANUALS_DIR="${REPO_ROOT}/docs/user-manuals"
MODELS_CONFIG="${HARNESS_ROOT}/config/models.json"
CONTEXT_MAP="${HARNESS_ROOT}/config/context-map.json"
STATE_DIR="${HARNESS_ROOT}/state"
LOOP_STATE="${STATE_DIR}/loop-state.json"
RUNS_DIR="${HARNESS_ROOT}/generated/runs"
SCREENSHOTS_ROOT="${RUNS_DIR}/screenshots"
TEST_CASES_DIR="${REPO_ROOT}/docs/test-cases"
COMMON_UI_UX_SUITE_DEFAULT="${HARNESS_ROOT}/test-cases/common/ui-ux-suite.json"
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

export HARNESS_ROOT REPO_ROOT BACKLOG TEST_CASE_INDEX PLAN_DIR TESTGEN_DOCS_MAP LOOP_CONFIG TESTGEN_CONFIG MODELS_CONFIG CONTEXT_MAP STATE_DIR RUNS_DIR SCREENSHOTS_ROOT TEST_CASES_DIR
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
  if [[ "$key" == "manualsgen" && -n "${AIH_MANUALSGEN_MODEL:-}" ]]; then
    echo "$AIH_MANUALSGEN_MODEL"
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
    aih_kv "ManualsGen" "$(get_model manualsgen)"
  else
    aih_kv "Agent" "not installed (curl https://cursor.com/install -fsS | bash)"
  fi
  aih_kv "Auth" "agent login (OAuth, one-time per machine)"
  aih_kv "Timeout" "idle $(get_agent_idle_timeout_ms)ms / max $(get_agent_timeout_ms)ms (AIH_AGENT_IDLE_TIMEOUT_MS / AIH_AGENT_TIMEOUT_MS)"
  local testgen_workers
  testgen_workers="$(get_testgen_workers)"
  if [[ "$testgen_workers" -gt 1 ]]; then
    aih_kv "TestGen workers" "$testgen_workers"
  fi
  aih_kv "Overrides" "AIH_MODEL=... AIH_SKIP_AGENT=1 AIH_SKIP_REVIEW=1"
}

AGENT_TIMEOUT_EXIT=124
AGENT_TIMEOUT_DEFAULT_MS=3600000
AGENT_IDLE_TIMEOUT_DEFAULT_MS=300000
AGENT_SHELL_TIMEOUT_DEFAULT_MS=900000
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
INTEGRATION_FAILURE_TRIAGE_JS="${HARNESS_ROOT}/scripts/lib/integration-failure-triage.js"

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
      hints+="- Failure in \`${path}\` is owned by slice \`${owner}\`, not \`${current_slice}\`. Owner slice must fix parallel test isolation (afterEach restore, dedicated section fixtures); signal \`SLICE_DEFER ${owner} <reason>\` or wait for harness auto-focus — **do not** resolve by bare re-run of \`aih:check\`."$'\n'
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
  local slice_id="${2:-}"
  if [[ -n "${AIH_AGENT_TIMEOUT_MS:-}" ]]; then
    echo "$AIH_AGENT_TIMEOUT_MS"
    return
  fi
  if [[ -n "$slice_id" ]]; then
    local override_ms
    override_ms="$(get_browser_test_timeout_ms "$slice_id" "$config" 2>/dev/null || true)"
    if [[ -n "$override_ms" ]]; then
      echo "$override_ms"
      return
    fi
  fi
  jq -r ".agent.timeoutMs // ${AGENT_TIMEOUT_DEFAULT_MS}" "$config"
}

get_browser_test_timeout_ms() {
  local slice_id="$1"
  local config="${2:-$LOOP_CONFIG}"
  [[ -n "$slice_id" ]] || return 1
  local ids_json minutes
  ids_json="$(jq -c '.browserTest.acceptanceSliceIds // []' "$config" 2>/dev/null || echo '[]')"
  if jq -e --arg id "$slice_id" '.[] | select(. == $id)' <<<"$ids_json" >/dev/null 2>&1; then
    minutes="$(jq -r '.browserTest.acceptanceSliceTimeoutMinutes // empty' "$config" 2>/dev/null || true)"
  else
    minutes="$(jq -r '.browserTest.timeoutMinutes // empty' "$config" 2>/dev/null || true)"
  fi
  [[ -n "$minutes" && "$minutes" != "null" ]] || return 1
  echo $((minutes * 60000))
}

get_agent_shell_timeout_ms() {
  local config="${1:-${AIH_HARNESS_CONFIG:-$LOOP_CONFIG}}"
  if [[ -n "${AIH_AGENT_SHELL_TIMEOUT_MS:-}" ]]; then
    echo "$AIH_AGENT_SHELL_TIMEOUT_MS"
    return
  fi
  jq -r ".agent.shellTimeoutMs // ${AGENT_SHELL_TIMEOUT_DEFAULT_MS}" "$config"
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

# Work-planner must not early-terminate on PLAN_DONE in assistant text — that signal
# fires before tool writes always flush to the host repo. Planner exits on result event only.
agent_work_planner_completion_signals_csv() {
  local config="${1:-${AIH_HARNESS_CONFIG:-$LOOP_CONFIG}}"
  jq -r '[.signals[]? // empty | select(. != "PLAN_DONE")] | unique | join(",")' "$config"
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
    local idle_ms signal_grace_ms result_grace_ms shell_ms signals_csv harness_config
    harness_config="${AIH_HARNESS_CONFIG:-$LOOP_CONFIG}"
    idle_ms="$(get_agent_idle_timeout_ms "$harness_config")"
    signal_grace_ms="$(get_agent_signal_grace_ms "$harness_config")"
    result_grace_ms="$(get_agent_result_grace_ms "$harness_config")"
    shell_ms="$(get_agent_shell_timeout_ms "$harness_config")"
    if [[ -n "${AIH_AGENT_COMPLETION_SIGNALS:-}" ]]; then
      signals_csv="$AIH_AGENT_COMPLETION_SIGNALS"
    else
      signals_csv="$(agent_completion_signals_csv "$harness_config")"
    fi
    stream_cmd=(node "${HARNESS_ROOT}/scripts/lib/stream-agent-output.js" \
      --outfile "$outfile" \
      --idle-timeout-ms "$idle_ms" \
      --max-timeout-ms "$timeout_ms" \
      --shell-timeout-ms "$shell_ms" \
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

# Unique per testgen-once invocation (parallel workers share second-granularity run_id()).
testgen_run_id() {
  local requirement_tag="${1:?requirement tag required}"
  local base="${AIH_RUN_ID:-$(run_id)}"
  local worker="${AIH_TESTGEN_WORKER_ID:-0}"
  local tag_safe="${requirement_tag//[^A-Za-z0-9._-]/_}"
  echo "${base}-${tag_safe}-w${worker}-$$"
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
  local spec_path ux_path web_port
  spec_path="$(playwright_spec_rel_path_for_slice "$slice_id")"
  ux_path="$(ux_bugs_path_for_slice_run "$slice_id" "$run_id")"
  web_port="$(aih_web_port)"
  cat <<EOF
## Post-verification — UX audit and Playwright regression (full phase only)

After all \`TC-*\` cases complete:

1. **UX audit** — review each screenshot per \`ai-harness/skills/ui-ux-testing/SKILL.md\`; log \`UX-${slice_id}-NNN\` bugs not already \`TC-*: FAIL\`
2. **Write UX bugs JSON:** \`${ux_path}\` (schema: \`ai-harness/schemas/ux-bugs.schema.json\`)
3. **Playwright codegen** — create or update \`${spec_path}\` per \`ai-harness/docs/playwright-regression.md\`
4. **Playwright config sanity** — read \`tests/playwright-ui/playwright.config.ts\` and \`src/support/constants.ts\`; \`baseURL\` / \`WEB_BASE_URL\` must target preview web (\`http://localhost:${web_port}\` or \`PLAYWRIGHT_BASE_URL\`). Fix imports/paths in owned spec/support files only.
5. **Harness config gate** — before this phase closes, the harness runs \`validate-playwright-ui-config.sh\` on your spec path. Ensure the spec compiles, imports resolve, and selectors match MCP-verified UI. Headless \`npx playwright test\` runs once in the next gate (\`run-checks --playwright-only\`).
6. Emit a plain line (no markdown/backticks): \`playwright-regression: ${spec_path} (N tests)\` before the signal line
7. Emit \`playwright-regression-run: PASS\` only after you believe the headless spec will pass (harness validates config before accepting \`BROWSER_TEST_PASS\`; headless run follows in the regression gate)
8. P0/P1 UX bugs block \`BROWSER_TEST_PASS\` even when all \`TC-*\` cases pass
EOF
}

resolve_playwright_spec_from_browser_output() {
  local slice_id="$1"
  local text_file="$2"
  local parse_line spec_path test_count

  if [[ -f "$text_file" ]] && parse_line="$(parse_playwright_regression_from_output "$text_file" 2>/dev/null)"; then
    spec_path="$(echo "$parse_line" | cut -f1)"
    test_count="$(jq_number_or_default "$(echo "$parse_line" | cut -f2)")"
    spec_path="$(normalize_repo_rel_path "$spec_path")"
    printf '%s\t%s\n' "$spec_path" "$test_count"
    return 0
  fi

  spec_path="$(resolve_playwright_spec_for_slice "$slice_id" 2>/dev/null || true)"
  spec_path="$(normalize_repo_rel_path "$spec_path")"
  [[ -n "$spec_path" ]] || return 1
  printf '%s\t0\n' "$spec_path"
}

run_playwright_ui_spec_rel() {
  local spec_rel="$1"
  local log_file="${2:-}"
  local pw_dir rel_spec label timeout_ms timeout_sec status

  spec_rel="$(normalize_repo_rel_path "$spec_rel")"
  [[ -n "$spec_rel" ]] || return 1
  [[ -f "${REPO_ROOT}/${spec_rel}" ]] || return 1

  pw_dir="${REPO_ROOT}/tests/playwright-ui"
  rel_spec="${spec_rel#tests/playwright-ui/}"
  if [[ "$rel_spec" == "$spec_rel" ]]; then
    if [[ "$spec_rel" == */scenarios/* ]]; then
      rel_spec="scenarios/$(basename "$spec_rel")"
    else
      rel_spec="$(basename "$spec_rel")"
    fi
  fi

  label="playwright slice spec (${rel_spec})"
  timeout_ms="$(get_check_command_timeout_ms "test:playwright-ui")"
  timeout_sec=$((timeout_ms / 1000))

  if [[ -n "$log_file" ]]; then
    aih_info "    log: ${log_file}"
    set +e
    run_check_with_timeout_ms "$timeout_ms" --log "$log_file" --label "$label" \
      bash -c "cd \"${pw_dir}\" && npx playwright test \"${rel_spec}\""
    status=$?
    set -e
  else
    set +e
    run_check_with_timeout_ms "$timeout_ms" --label "$label" \
      bash -c "cd \"${pw_dir}\" && npx playwright test \"${rel_spec}\""
    status=$?
    set -e
  fi

  if [[ "$status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
    aih_check_fail "${label} (timed out after ${timeout_sec}s)"
    return "$status"
  fi
  if [[ "$status" -ne 0 ]]; then
    [[ -n "$log_file" ]] && emit_check_log_tail "$log_file" 40
    aih_check_fail "${label} (exit ${status})"
    return "$status"
  fi
  aih_check_ok "$label"
  return 0
}

# Playwright UI config validation before browser-test phase closes (full phase).
# Headless regression runs once in run-checks.sh --playwright-only (ralph-once or standalone browser test).
verify_playwright_ui_for_browser_test_close() {
  local slice_id="$1"
  local text_file="$2"
  local log_file="$3"
  local resolved spec_path test_count

  if ! slice_requires_playwright_regression_gate "$slice_id"; then
    aih_info "Playwright UI verification skipped (regression gate not required for ${slice_id})"
    return 0
  fi

  if ! resolved="$(resolve_playwright_spec_from_browser_output "$slice_id" "$text_file")"; then
    aih_err "Playwright UI verification failed: no spec path for ${slice_id}"
    return 1
  fi
  spec_path="$(echo "$resolved" | cut -f1)"
  test_count="$(echo "$resolved" | cut -f2)"

  if [[ "$test_count" -eq 0 ]]; then
    aih_warn "Playwright spec reports 0 tests — skipping Playwright UI config validation"
    return 0
  fi

  : >"$log_file"
  {
    echo "==> Validating Playwright UI workspace config"
    "${HARNESS_ROOT}/scripts/validate-playwright-ui-config.sh" "$slice_id" "$spec_path"
  } >>"$log_file" 2>&1 || {
    cat "$log_file" >&2
    return 1
  }
  return 0
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

count_playwright_tests_in_spec() {
  local spec_rel="$1"
  local spec_path
  spec_rel="$(normalize_repo_rel_path "$spec_rel")"
  [[ -n "$spec_rel" ]] || { echo 0; return; }
  spec_path="${REPO_ROOT}/${spec_rel}"
  [[ -f "$spec_path" ]] || { echo 0; return; }
  grep -cE '^\s*test\(' "$spec_path" 2>/dev/null || echo 0
}

# Resolve playwright spec path + test count from agent output, with on-disk fallback.
resolve_playwright_regression_for_pass() {
  local slice_id="$1"
  local text_file="$2"
  local parse_line spec_path test_count synthesized_line

  if parse_line="$(parse_playwright_regression_from_output "$text_file" 2>/dev/null)"; then
    spec_path="$(echo "$parse_line" | cut -f1)"
    test_count="$(jq_number_or_default "$(echo "$parse_line" | cut -f2)")"
    spec_path="$(normalize_repo_rel_path "$spec_path")"
    printf '%s\t%s\n' "$spec_path" "$test_count"
    return 0
  fi

  spec_path="$(resolve_playwright_spec_for_slice "$slice_id" 2>/dev/null || true)"
  spec_path="$(normalize_repo_rel_path "$spec_path")"
  [[ -n "$spec_path" && -f "${REPO_ROOT}/${spec_path}" ]] || return 1
  test_count="$(count_playwright_tests_in_spec "$spec_path")"
  [[ "$test_count" -gt 0 ]] || return 1
  synthesized_line="playwright-regression: ${spec_path} (${test_count} tests)"
  aih_warn "Browser test output missing playwright-regression line — using on-disk spec ${spec_path} (${test_count} tests)"
  {
    echo ""
    echo "## Harness fallback — synthesized playwright-regression line"
    echo "$synthesized_line"
  } >>"$text_file"
  printf '%s\t%s\n' "$spec_path" "$test_count"
  return 0
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
  spec_path="$(normalize_repo_rel_path "$spec_path")"
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

TESTGEN_VALIDATION_FEEDBACK_DIR="${STATE_DIR}/testgen-validation-feedback"

testgen_validation_feedback_path() {
  local requirement_tag="$1"
  echo "${TESTGEN_VALIDATION_FEEDBACK_DIR}/${requirement_tag}.txt"
}

write_testgen_validation_feedback() {
  local requirement_tag="$1"
  local feedback="$2"
  mkdir -p "$TESTGEN_VALIDATION_FEEDBACK_DIR"
  printf '%s\n' "$feedback" > "$(testgen_validation_feedback_path "$requirement_tag")"
}

clear_testgen_validation_feedback() {
  local path
  path="$(testgen_validation_feedback_path "$1")"
  [[ -f "$path" ]] && rm -f "$path"
}

format_testgen_validation_feedback_block() {
  local requirement_tag="$1"
  local path line
  path="$(testgen_validation_feedback_path "$requirement_tag")"
  [[ -f "$path" ]] || return 0

  cat <<EOF
## Previous validation failure (fix before TESTGEN_DONE)

The last harness run for this tag **failed validation**. Update the artifact at \`$(test_case_artifact_path "$requirement_tag")\` so \`validate-test-cases.sh\` passes — address **every** item below:

EOF
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    echo "- ${line}"
  done < "$path"
  echo ""
}

PLAN_VALIDATION_FEEDBACK_DIR="${STATE_DIR}/plan-validation-feedback"

plan_validation_feedback_path() {
  local slice_id="$1"
  echo "${PLAN_VALIDATION_FEEDBACK_DIR}/${slice_id}.txt"
}

write_plan_validation_feedback() {
  local slice_id="$1"
  local feedback="$2"
  mkdir -p "$PLAN_VALIDATION_FEEDBACK_DIR"
  printf '%s\n' "$feedback" > "$(plan_validation_feedback_path "$slice_id")"
}

clear_plan_validation_feedback() {
  local path
  path="$(plan_validation_feedback_path "$1")"
  [[ -f "$path" ]] && rm -f "$path"
}

format_plan_validation_feedback_block() {
  local slice_id="$1"
  local path line
  path="$(plan_validation_feedback_path "$slice_id")"
  [[ -f "$path" ]] || return 0

  cat <<EOF
## Previous plan validation failure (fix before PLAN_DONE)

The last harness run for this slice **failed plan validation**. Fix **every** item below in your next plan output. Do not replan unrelated sections or re-read the full doc tree first.

EOF
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    echo "- ${line}"
  done < "$path"
  echo ""
}

format_existing_artifact_review_block() {
  local requirement_tag="$1"
  local artifact_path artifact_abs mode case_count id_list stored_fp feedback_path status_line
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
  stored_fp="$(jq_generation_index_read "$TEST_CASE_INDEX" --arg id "$requirement_tag" '.[0] | .tags[$id].docFingerprint // ""')"
  feedback_path="$(testgen_validation_feedback_path "$requirement_tag")"
  if [[ -f "$feedback_path" ]]; then
    status_line="**failed harness validation** — fix errors listed under **Previous validation failure** below"
  elif [[ -n "$stored_fp" && "$stored_fp" != "null" ]]; then
    status_line="**out of date** (\`test-case-index.json\` marks this tag \`current: false\` — docs changed since last generation)"
  else
    status_line="**present but not yet accepted** — update until harness validation passes"
  fi

  cat <<EOF
## Review and update existing artifact

The test case artifact at \`${artifact_path}\` is ${status_line}.

**Read the existing file first.** Update only what current docs and harness validation require — do not rewrite from scratch unless necessary.

### Review rules

1. **Keep** cases that still match current docs; edit only affected fields (\`traceability\`, \`title\`, \`preconditions\`, \`steps\`, \`expected\`, \`edgeCase\`, \`priority\`, \`technique\`, \`layer\`, \`category\`).
2. **Add** cases for new doc requirements, coverage gaps, or missing required techniques (self-check below). Append new IDs; do not renumber existing ones.
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
    if [[ -f "$(testgen_validation_feedback_path "$requirement_tag")" ]]; then
      echo "Finish in **one pass** — fix every validation error listed above, then re-run self-check. Generate specs only — no implementation."
      return 0
    fi
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

# test-case-index.json and manuals-index.json must be exactly one JSON object.
# Planner agents sometimes append a second copy; plain jq reads/writes every value
# and preserves duplication. Always use -s '.[0] | …'; writers collapse on save.
jq_generation_index_read() {
  local file="$1"
  shift
  jq -r -s "$@" "$file"
}

jq_generation_index_update() {
  local file="$1"
  local filter="$2"
  shift 2
  local tmp
  tmp="$(mktemp)"
  jq -s "$@" "$filter" "$file" > "$tmp" && mv "$tmp" "$file"
}

list_stale_requirement_tags() {
  jq_generation_index_read "$TEST_CASE_INDEX" '
    .[0] | .tags | to_entries[] | select(.value.current == false) | .key
  ' 2>/dev/null || true
}

requirement_tag_test_cases_current() {
  local requirement_tag="$1"
  local current
  current="$(jq_generation_index_read "$TEST_CASE_INDEX" --arg id "$requirement_tag" '.[0] | .tags[$id].current // false')"
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

TESTGEN_STATE_LOCK="${STATE_DIR}/.testgen.lock.d"

get_testgen_workers() {
  local workers="${AIH_TESTGEN_WORKERS:-}"
  if [[ -z "$workers" ]]; then
    workers="$(jq -r '.parallelism.workers // 1' "$TESTGEN_CONFIG" 2>/dev/null || echo 1)"
  fi
  if [[ ! "$workers" =~ ^[0-9]+$ ]] || [[ "$workers" -lt 1 ]]; then
    workers=1
  fi
  echo "$workers"
}

get_testgen_tag_max_retries() {
  if [[ -n "${AIH_TESTGEN_TAG_MAX_RETRIES:-}" ]]; then
    echo "$AIH_TESTGEN_TAG_MAX_RETRIES"
    return
  fi
  jq -r '.tagMaxRetries // 5' "$TESTGEN_CONFIG" 2>/dev/null || echo 5
}

get_testgen_worker_timeout_ms() {
  local tag_count="${1:-1}"
  if [[ ! "$tag_count" =~ ^[0-9]+$ ]] || [[ "$tag_count" -lt 1 ]]; then
    tag_count=1
  fi
  if [[ -n "${AIH_TESTGEN_WORKER_TIMEOUT_MS:-}" ]]; then
    echo "$AIH_TESTGEN_WORKER_TIMEOUT_MS"
    return
  fi
  local per_tag_ms configured
  configured="$(jq -r '.parallelism.workerTimeoutMs // empty' "$TESTGEN_CONFIG" 2>/dev/null || true)"
  if [[ -n "$configured" && "$configured" != "null" ]]; then
    per_tag_ms="$configured"
  else
    local agent_ms max_retries
    agent_ms="$(get_agent_timeout_ms "$TESTGEN_CONFIG")"
    max_retries="$(get_testgen_tag_max_retries)"
    per_tag_ms=$(( max_retries * agent_ms + max_retries * 120000 + 120000 ))
  fi
  echo $(( per_tag_ms * tag_count ))
}

list_pending_requirement_tags() {
  local tag
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    if ! requirement_tag_test_cases_current "$tag"; then
      echo "$tag"
    fi
  done < <(all_requirement_tags_sorted)
}

# Run testgen-once for one tag until current or non-retryable failure (TESTGEN_BLOCKED).
run_testgen_tag_until_current() {
  local tag="$1"
  local worker_id="${2:-${AIH_TESTGEN_WORKER_ID:-0}}"
  local attempt=0
  local max_retries status=0
  local tag_safe agent_out

  max_retries="$(get_testgen_tag_max_retries)"

  while ! requirement_tag_test_cases_current "$tag"; do
    attempt=$((attempt + 1))
    if [[ "$attempt" -gt "$max_retries" ]]; then
      aih_err "TestGen exhausted ${max_retries} retries for ${tag}"
      return 1
    fi
    if [[ "$attempt" -gt 1 ]]; then
      aih_warn "TestGen retry attempt ${attempt}/${max_retries} for ${tag}"
    fi

    set +e
    "${HARNESS_ROOT}/scripts/testgen-once.sh" "$tag"
    status=$?
    set -e

    if requirement_tag_test_cases_current "$tag"; then
      return 0
    fi

    tag_safe="${tag//[^A-Za-z0-9._-]/_}"
    agent_out="$(ls -t "${RUNS_DIR}/${AIH_RUN_ID:-*}-${tag_safe}-w${worker_id}-"*-testgen.txt 2>/dev/null | head -1 || true)"
    if [[ -n "$agent_out" && -f "$agent_out" ]] && grep -q "TESTGEN_BLOCKED" "$agent_out"; then
      aih_warn "${tag} blocked — stopping retries"
      return 1
    fi
  done
  return 0
}

testgen_worker_tags_file() {
  local run_id="$1"
  local worker_id="$2"
  echo "${RUNS_DIR}/${run_id}-testgen-worker-${worker_id}.tags"
}

write_testgen_worker_tags_file() {
  local run_id="$1"
  local worker_id="$2"
  shift 2
  local outfile tag
  outfile="$(testgen_worker_tags_file "$run_id" "$worker_id")"
  ensure_runs_dir
  : > "$outfile"
  while [[ "$#" -gt 0 ]]; do
    tag="$1"
    shift
    [[ -z "$tag" ]] && continue
    echo "$tag" >> "$outfile"
  done
  echo "$outfile"
}

assign_testgen_worker_tag_files() {
  local run_id="$1"
  local workers="$2"
  shift 2
  local -a tags=("$@")
  local total="${#tags[@]}"
  local base remainder offset chunk w outfile

  if [[ "$total" -eq 0 ]]; then
    local w_empty
    for ((w_empty=1; w_empty<=workers; w_empty++)); do
      write_testgen_worker_tags_file "$run_id" "$w_empty"
    done
    return 0
  fi

  base=$((total / workers))
  remainder=$((total % workers))
  offset=0
  for ((w=1; w<=workers; w++)); do
    if [[ "$base" -eq 0 && "$remainder" -gt 0 ]]; then
      if [[ "$w" -le "$remainder" ]]; then
        chunk=1
      else
        chunk=0
      fi
    elif [[ "$w" -lt "$workers" ]]; then
      chunk=$base
    else
      chunk=$((base + remainder))
    fi
    if [[ "$chunk" -gt 0 ]]; then
      outfile="$(write_testgen_worker_tags_file "$run_id" "$w" "${tags[@]:$offset:$chunk}")"
    else
      outfile="$(write_testgen_worker_tags_file "$run_id" "$w")"
    fi
    printf '%s\n' "$outfile"
    offset=$((offset + chunk))
  done
}

with_testgen_state_lock() {
  local lock_dir="$TESTGEN_STATE_LOCK"
  local waited=0
  until mkdir "$lock_dir" 2>/dev/null; do
    if [[ "$waited" -ge 300 ]]; then
      echo "ERROR: testgen state lock timeout (${lock_dir})" >&2
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done

  local status=0
  "$@" || status=$?
  rmdir "$lock_dir" 2>/dev/null || true
  return "$status"
}

finalize_testgen_pass() {
  local requirement_tag="$1"
  local doc_fp="$2"
  clear_testgen_validation_feedback "$requirement_tag"
  "${HARNESS_ROOT}/scripts/sync-test-cases-to-backlog.sh" "$requirement_tag"
  mark_test_cases_current "$requirement_tag" "$doc_fp"
  append_progress "$requirement_tag" "testgen_passed"
  local commit_on_pass
  commit_on_pass="$(jq -r '.loop.commitOnPass // true' "$TESTGEN_CONFIG")"
  if [[ "$commit_on_pass" == "true" ]]; then
    "${HARNESS_ROOT}/scripts/git-commit-testgen.sh" "$requirement_tag"
  fi
}

prefix_testgen_worker_output() {
  local worker_id="$1"
  while IFS= read -r line || [[ -n "$line" ]]; do
    printf '[worker-%s] %s\n' "$worker_id" "$line"
  done
}

count_pending_requirement_tags() {
  local pending=0 remaining=0 tag
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    remaining=$((remaining + 1))
    if ! requirement_tag_test_cases_current "$tag"; then
      pending=$((pending + 1))
    fi
  done < <(all_requirement_tags_sorted)
  echo "${pending} ${remaining}"
}

# --- ManualsGen ---

get_manual_item_json() {
  local item_id="$1"
  jq -c --arg id "$item_id" '.items[] | select(.id == $id)' "$MANUALS_BACKLOG" 2>/dev/null | head -1
}

manual_item_field() {
  local item_id="$1"
  local field="$2"
  get_manual_item_json "$item_id" | jq -r --arg f "$field" '.[$f] // empty'
}

manual_artifact_path() {
  local item_id="$1"
  manual_item_field "$item_id" outputPath
}

manual_artifact_abs() {
  echo "${REPO_ROOT}/$(manual_artifact_path "$1")"
}

all_manual_item_ids_sorted() {
  jq -r '.items[] | "\(.priority)\t\(.id)"' "$MANUALS_BACKLOG" 2>/dev/null | sort -n | cut -f2-
}

manual_item_type() {
  manual_item_field "$1" type
}

manual_item_current() {
  local item_id="$1"
  local current
  current="$(jq_generation_index_read "$MANUALS_INDEX" --arg id "$item_id" '.[0] | .tags[$id].current // false')"
  [[ "$current" == "true" ]]
}

all_flow_manuals_current() {
  local item_id item_type
  while IFS= read -r item_id; do
    [[ -z "$item_id" ]] && continue
    item_type="$(manual_item_type "$item_id")"
    [[ "$item_type" == "flow" ]] || continue
    if ! manual_item_current "$item_id"; then
      return 1
    fi
  done < <(all_manual_item_ids_sorted)
  return 0
}

implementation_gate_blocks_manualsgen() {
  local mode require_all
  mode="$(jq -r '.implementationGate.mode // "optional"' "$MANUALSGEN_CONFIG" 2>/dev/null || echo optional)"
  require_all="$(jq -r '.implementationGate.requireAllSlicesPass // false' "$MANUALSGEN_CONFIG" 2>/dev/null || echo false)"
  [[ "$mode" == "required" || "$require_all" == "true" ]] || return 1
  ! all_slices_pass
}

all_manuals_current() {
  local item_id
  while IFS= read -r item_id; do
    [[ -z "$item_id" ]] && continue
    if ! manual_item_current "$item_id"; then
      return 1
    fi
  done < <(all_manual_item_ids_sorted)
  return 0
}

pick_next_manualsgen_item() {
  local item_id item_type
  if implementation_gate_blocks_manualsgen; then
    echo ""
    return 0
  fi
  while IFS= read -r item_id; do
    [[ -z "$item_id" ]] && continue
    if manual_item_current "$item_id"; then
      continue
    fi
    item_type="$(manual_item_type "$item_id")"
    if [[ "$item_type" == "runbook" ]] && ! all_flow_manuals_current; then
      continue
    fi
    echo "$item_id"
    return 0
  done < <(all_manual_item_ids_sorted)
  echo ""
}

mark_manual_current() {
  local item_id="$1"
  local fingerprint="$2"
  local generated_at="${3:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
  jq_generation_index_update "$MANUALS_INDEX" '
    .[0] | .tags[$id] = {
      current: true,
      docFingerprint: $fp,
      generatedAt: $ts
    }
  ' --arg id "$item_id" --arg fp "$fingerprint" --arg ts "$generated_at"
}

reset_manual_item_on_doc_drift() {
  local item_id="$1"
  local live_fp="$2"
  jq_generation_index_update "$MANUALS_INDEX" '
    .[0] | .tags[$id] = {
      current: false,
      docFingerprint: $fp,
      generatedAt: null
    }
  ' --arg id "$item_id" --arg fp "$live_fp"
  append_guardrail "$item_id" "Manual source docs changed — run ManualsGen (index current=false; fingerprint=${live_fp})"
}

manualsgen_regeneration_mode() {
  jq -r '.regeneration.mode // "incremental"' "$MANUALSGEN_CONFIG" 2>/dev/null || echo "incremental"
}

format_existing_manual_review_block() {
  local item_id="$1"
  local artifact_path artifact_abs mode stored_fp line_count
  artifact_path="$(manual_artifact_path "$item_id")"
  artifact_abs="$(manual_artifact_abs "$item_id")"
  mode="$(manualsgen_regeneration_mode)"

  if [[ ! -f "$artifact_abs" ]]; then
    return 0
  fi

  if [[ "$mode" == "full" ]]; then
    cat <<EOF
## Existing manual (reference)

A manual already exists at \`${artifact_path}\`. Regeneration mode is **full** — rewrite from current docs.

EOF
    return 0
  fi

  line_count="$(wc -l < "$artifact_abs" | tr -d ' ')"
  stored_fp="$(jq_generation_index_read "$MANUALS_INDEX" --arg id "$item_id" '.[0] | .tags[$id].docFingerprint // ""')"

  cat <<EOF
## Review and update existing manual

The manual at \`${artifact_path}\` is **out of date** (\`manuals-index.json\` marks this item \`current: false\`).

**Read the existing file first.** Update only what current docs require.

- **Path:** \`${artifact_path}\`
- **Line count:** ${line_count}
$( [[ -n "$stored_fp" && "$stored_fp" != "null" ]] && printf '- **Index fingerprint:** `%s`\n' "$stored_fp" )

EOF
}

mark_test_cases_current() {
  local requirement_tag="$1"
  local fingerprint="$2"
  local generated_at="${3:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
  jq_generation_index_update "$TEST_CASE_INDEX" '
    .[0] | .tags[$id] = {
      current: true,
      docFingerprint: $fp,
      generatedAt: $ts
    }
  ' --arg id "$requirement_tag" --arg fp "$fingerprint" --arg ts "$generated_at"
  mark_slices_stale_for_tag "$requirement_tag"
}

_reset_requirement_tag_on_doc_drift_body() {
  local requirement_tag="$1"
  local live_fp="$2"
  ensure_test_case_artifact_restored "$requirement_tag"
  jq_generation_index_update "$TEST_CASE_INDEX" '
    .[0] | .tags[$id] = {
      current: false,
      docFingerprint: $fp,
      generatedAt: null
    }
  ' --arg id "$requirement_tag" --arg fp "$live_fp"
  mark_slices_stale_for_tag "$requirement_tag"
  append_guardrail "$requirement_tag" "Docs changed — run TestGen before Ralph (index current=false; fingerprint=${live_fp})"
}

reset_requirement_tag_on_doc_drift() {
  with_testgen_state_lock _reset_requirement_tag_on_doc_drift_body "$@"
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

playwright_is_slice_spec_path() {
  local path
  path="$(normalize_repo_rel_path "$1")"
  [[ -n "$path" ]] || return 1
  [[ "$path" =~ ^tests/playwright-ui/scenarios/.+\.spec\.ts$ ]]
}

resolve_playwright_spec_for_slice() {
  local slice_id="$1"
  local slice_json spec candidate normalized
  slice_json="$(get_slice_json "$slice_id")"
  [[ -z "$slice_json" || "$slice_json" == "null" ]] && return 1

  while IFS= read -r candidate; do
    [[ -z "$candidate" ]] && continue
    normalized="$(normalize_repo_rel_path "$candidate")"
    if playwright_is_slice_spec_path "$normalized" && [[ -e "$REPO_ROOT/$normalized" ]]; then
      echo "$normalized"
      return 0
    fi
  done < <(echo "$slice_json" | jq -r '.testRequirements.playwright[]? // empty')

  spec="$(playwright_spec_rel_path_for_slice "$slice_id")"
  if [[ -e "$REPO_ROOT/$spec" ]]; then
    echo "$spec"
    return 0
  fi

  if [[ -f "$PLAYWRIGHT_REGRESSION_INDEX" ]]; then
    spec="$(jq -r --arg id "$slice_id" '.slices[$id].specPath // empty' "$PLAYWRIGHT_REGRESSION_INDEX")"
    spec="$(normalize_repo_rel_path "$spec")"
    if playwright_is_slice_spec_path "$spec" && [[ -e "$REPO_ROOT/$spec" ]]; then
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

  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    allowlist+=("$path")
  done < <(echo "$slice_json" | jq -r '.scopeExtensions[]?.path // empty')

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

playwright_support_dir_rel() {
  echo "tests/playwright-ui/src/support"
}

normalize_repo_rel_path() {
  local path="$1"
  [[ -n "$path" ]] || return 0
  if [[ "$path" == "$REPO_ROOT/"* ]]; then
    path="${path#"$REPO_ROOT"/}"
  fi
  path="${path#./}"
  printf '%s\n' "$path"
}

# Register committed Playwright spec in slice allowlist (tester cannot edit backlog directly).
sync_playwright_spec_to_backlog() {
  local slice_id="$1"
  local spec_path="$2"
  spec_path="$(normalize_repo_rel_path "$spec_path")"
  [[ -n "$spec_path" ]] || return 0

  local tmp
  tmp="$(mktemp)"
  jq --arg id "$slice_id" --arg spec "$spec_path" '
    .slices |= map(
      if .id == $id then
        .testRequirements = (.testRequirements // {})
        | (.testRequirements.playwright // []) as $rest
        | .testRequirements.playwright = (
            reduce ([$spec] + $rest)[] as $item ([]; if (index($item) != null) then . else . + [$item] end)
          )
      else . end
    )
  ' "$BACKLOG" >"$tmp" && mv "$tmp" "$BACKLOG"
}

# Paths written by the browser-test gate after implementer scope already passed.
browser_test_owned_paths() {
  local slice_id="$1"
  local run_id="${2:-}"
  local spec_path="${3:-}"
  if [[ -z "$spec_path" ]]; then
    spec_path="$(playwright_spec_rel_path_for_slice "$slice_id")"
  else
    spec_path="$(normalize_repo_rel_path "$spec_path")"
  fi
  printf '%s\n' \
    "ai-harness/playwright-regression-index.json" \
    "$spec_path" \
    "$(playwright_support_dir_rel)"
  if [[ -n "$run_id" ]]; then
    printf '%s\n' "ai-harness/generated/runs/ux-bugs/${slice_id}/${run_id}.json"
  fi
  printf '%s\n' "ai-harness/generated/runs/screenshots/${slice_id}/browser-test"
  local ref
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    printf '%s\n' "$(test_case_artifact_path "$ref")"
  done < <(slice_product_item_refs "$slice_id" 2>/dev/null || true)
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

revert_browser_test_workspace_changes() {
  local slice_id="$1"
  local run_id="${2:-}"
  local spec_path="${3:-}"
  if ! git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    return 0
  fi

  local prev_cwd="$PWD"
  cd "$REPO_ROOT"

  local -a owned_prefixes=() restore_paths=() clean_paths=()
  local file_path owned_path is_owned

  while IFS= read -r owned_path; do
    [[ -z "$owned_path" ]] && continue
    owned_prefixes+=("$owned_path")
  done < <(browser_test_owned_paths "$slice_id" "$run_id" "$spec_path")

  while IFS= read -r file_path; do
    [[ -z "$file_path" ]] && continue
    is_owned=false
    for owned_path in "${owned_prefixes[@]}"; do
      if [[ "$file_path" == "$owned_path" || "$file_path" == "${owned_path}/"* ]]; then
        is_owned=true
        break
      fi
    done
    if [[ "$is_owned" != true ]]; then
      continue
    fi
    if git -C "$REPO_ROOT" ls-files --error-unmatch "$file_path" >/dev/null 2>&1; then
      restore_paths+=("$file_path")
    else
      clean_paths+=("$file_path")
    fi
  done < <(git_changed_files)

  if ((${#restore_paths[@]} > 0)); then
    git -C "$REPO_ROOT" restore -- "${restore_paths[@]}" 2>/dev/null || true
  fi

  if ((${#clean_paths[@]} > 0)); then
    for file_path in "${clean_paths[@]}"; do
      if [[ -d "$REPO_ROOT/$file_path" ]]; then
        rm -rf "$REPO_ROOT/$file_path"
      elif [[ -f "$REPO_ROOT/$file_path" ]]; then
        rm -f "$REPO_ROOT/$file_path"
      fi
    done
  fi

  if ((${#restore_paths[@]} > 0 || ${#clean_paths[@]} > 0)); then
    aih_warn "Reverted browser-test-owned workspace changes for slice ${slice_id} (${#restore_paths[@]} tracked, ${#clean_paths[@]} untracked)"
  fi

  cd "$prev_cwd" || true
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

agent_invoke_manualsgen() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args fmt
  args=(-p --force --trust --model "$model")
  read -ra fmt <<< "$(agent_output_format_args)"
  args+=("${fmt[@]}")
  local timeout_ms idle_config
  idle_config="$MANUALSGEN_CONFIG"
  timeout_ms="$(get_agent_timeout_ms "$idle_config")"
  AIH_HARNESS_CONFIG="$idle_config" run_agent_with_timeout_ms "$timeout_ms" "$outfile" "$AGENT_BIN" "${args[@]}" "$prompt"
}

# Work planner: writes plan markdown only (no product code).
agent_invoke_work_planner() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args fmt
  args=(-p --force --trust --model "$model")
  read -ra fmt <<< "$(agent_output_format_args)"
  args+=("${fmt[@]}")
  local timeout_ms idle_config planner_signals
  idle_config="$LOOP_CONFIG"
  timeout_ms="$(get_agent_timeout_ms "$idle_config")"
  planner_signals="$(agent_work_planner_completion_signals_csv "$idle_config")"
  AIH_AGENT_COMPLETION_SIGNALS="$planner_signals" \
    AIH_HARNESS_CONFIG="$idle_config" \
    run_agent_with_timeout_ms "$timeout_ms" "$outfile" "$AGENT_BIN" "${args[@]}" "$prompt"
}

# Ephemeral per-iteration plan (generated/runs, not committed). Injected into implementer prompt.
work_plan_run_path() {
  local run_id="$1"
  echo "ai-harness/generated/runs/${run_id}-work-plan.md"
}

work_plan_run_abs() {
  local run_id="$1"
  echo "${REPO_ROOT}/$(work_plan_run_path "$run_id")"
}

resolve_work_plan_file_for_prompt() {
  if [[ -n "${AIH_WORK_PLAN_FILE:-}" && -f "${AIH_WORK_PLAN_FILE}" ]]; then
    printf '%s' "${AIH_WORK_PLAN_FILE}"
    return 0
  fi
  if [[ -n "${AIH_RUN_ID:-}" ]]; then
    local run_plan
    run_plan="$(work_plan_run_abs "$AIH_RUN_ID")"
    if [[ -f "$run_plan" ]]; then
      printf '%s' "$run_plan"
      return 0
    fi
  fi
  return 1
}

# Legacy path under ai-harness/plans/ — manual validate only; Ralph does not write here.
work_plan_artifact_path() {
  local slice_id="$1"
  local custom
  custom="$(get_slice_field "$slice_id" planArtifact 2>/dev/null || echo "")"
  if [[ -n "$custom" && "$custom" != "null" ]]; then
    echo "$custom"
    return 0
  fi
  echo "ai-harness/plans/${slice_id}.md"
}

work_plan_artifact_abs() {
  local slice_id="$1"
  echo "${REPO_ROOT}/$(work_plan_artifact_path "$slice_id")"
}

slice_requires_plan() {
  local slice_id="$1"
  local explicit agent_type require_explicit
  explicit="$(get_slice_field "$slice_id" requiresPlan 2>/dev/null || echo "")"
  if [[ "$explicit" == "false" ]]; then
    return 1
  fi
  if [[ "$explicit" == "true" ]]; then
    return 0
  fi
  require_explicit="$(jq -r '.workPlanGate.requireExplicitRequiresPlan // false' "$LOOP_CONFIG" 2>/dev/null || echo false)"
  if [[ "$require_explicit" == "true" ]]; then
    return 1
  fi
  agent_type="$(get_slice_field "$slice_id" agent 2>/dev/null || echo "backend")"
  [[ "$agent_type" != "infra" ]]
}

work_plan_gate_mode() {
  local mode
  mode="$(jq -r '.workPlanGate.mode // "required"' "$LOOP_CONFIG" 2>/dev/null || echo required)"
  echo "$mode"
}

work_plan_gate_max_retries() {
  if [[ -n "${AIH_WORK_PLAN_MAX_RETRIES:-}" ]]; then
    echo "$AIH_WORK_PLAN_MAX_RETRIES"
    return
  fi
  jq -r '.workPlanGate.maxRetries // 5' "$LOOP_CONFIG" 2>/dev/null || echo 5
}

work_plan_gate_artifact_wait_ms() {
  if [[ -n "${AIH_WORK_PLAN_ARTIFACT_WAIT_MS:-}" ]]; then
    echo "$AIH_WORK_PLAN_ARTIFACT_WAIT_MS"
    return
  fi
  jq -r '.workPlanGate.artifactWaitMs // 30000' "$LOOP_CONFIG" 2>/dev/null || echo 30000
}

work_plan_gate_artifact_poll_ms() {
  if [[ -n "${AIH_WORK_PLAN_ARTIFACT_POLL_MS:-}" ]]; then
    echo "$AIH_WORK_PLAN_ARTIFACT_POLL_MS"
    return
  fi
  jq -r '.workPlanGate.artifactPollMs // 500' "$LOOP_CONFIG" 2>/dev/null || echo 500
}

# Poll until ephemeral plan markdown exists and is non-empty (post-agent fs flush).
wait_for_plan_file() {
  local plan_file="$1"
  local wait_ms poll_ms elapsed=0
  wait_ms="$(work_plan_gate_artifact_wait_ms)"
  poll_ms="$(work_plan_gate_artifact_poll_ms)"
  while [[ "$elapsed" -lt "$wait_ms" ]]; do
    if [[ -f "$plan_file" && -s "$plan_file" ]]; then
      return 0
    fi
    sleep "$(awk "BEGIN { printf \"%.3f\", ${poll_ms} / 1000 }")"
    elapsed=$((elapsed + poll_ms))
  done
  [[ -f "$plan_file" && -s "$plan_file" ]]
}

# Wait until plan file size is stable (agent may still be flushing a follow-up edit).
wait_for_plan_file_stable() {
  local plan_file="$1"
  local wait_ms poll_ms elapsed=0 prev_size=-1 stable_polls=0 size
  wait_ms="$(work_plan_gate_artifact_wait_ms)"
  poll_ms="$(work_plan_gate_artifact_poll_ms)"
  while [[ "$elapsed" -lt "$wait_ms" ]]; do
    if [[ -f "$plan_file" && -s "$plan_file" ]]; then
      size="$(wc -c < "$plan_file" | tr -d ' ')"
      if [[ "$prev_size" -ge 0 && "$size" == "$prev_size" ]]; then
        stable_polls=$((stable_polls + 1))
        if [[ "$stable_polls" -ge 2 ]]; then
          return 0
        fi
      else
        stable_polls=0
        prev_size="$size"
      fi
    else
      stable_polls=0
      prev_size=-1
    fi
    sleep "$(awk "BEGIN { printf \"%.3f\", ${poll_ms} / 1000 }")"
    elapsed=$((elapsed + poll_ms))
  done
  [[ -f "$plan_file" && -s "$plan_file" ]]
}

validate_work_plan_artifact_quiet() {
  local slice_id="$1"
  local plan_file="$2"
  local out rc
  set +e
  out="$(./ai-harness/scripts/validate-work-plan.sh "$slice_id" --quiet --plan-file "$plan_file" 2>&1)"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    write_plan_validation_feedback "$slice_id" "$out"
    return 1
  fi
  clear_plan_validation_feedback "$slice_id"
  return 0
}

finalize_ephemeral_work_plan() {
  local slice_id="$1"
  local plan_file="$2"
  local artifact_wait_ms rel_path validate_rc=0
  set +e
  artifact_wait_ms="$(work_plan_gate_artifact_wait_ms)"
  rel_path="${plan_file#${REPO_ROOT}/}"

  if ! wait_for_plan_file_stable "$plan_file"; then
    write_plan_validation_feedback "$slice_id" "$(plan_artifact_missing_feedback "$slice_id" "$rel_path" "$artifact_wait_ms")"
    aih_err "Work plan missing at ${rel_path} after ${artifact_wait_ms}ms wait"
    return 1
  fi

  validate_work_plan_artifact_quiet "$slice_id" "$plan_file"
  validate_rc=$?
  if [[ "$validate_rc" -ne 0 ]]; then
    sleep "$(awk "BEGIN { printf \"%.3f\", $(work_plan_gate_artifact_poll_ms) / 1000 }")"
    wait_for_plan_file_stable "$plan_file"
    validate_work_plan_artifact_quiet "$slice_id" "$plan_file"
    validate_rc=$?
  fi
  if [[ "$validate_rc" -ne 0 ]]; then
    aih_err "Work plan validation failed for ${slice_id} — see state/plan-validation-feedback/${slice_id}.txt"
    return 1
  fi
  aih_ok "Work plan validated: ${rel_path}"
  return 0
}

plan_artifact_missing_feedback() {
  local slice_id="$1"
  local rel_path="$2"
  local wait_ms="$3"
  cat <<EOF
Plan markdown not found at ${rel_path} after agent exit (waited ${wait_ms}ms).
Write the implementation plan with the editor Write tool to exactly: ${rel_path}
Do not only print the plan in chat. Read the file back to confirm it is non-empty before emitting PLAN_DONE ${slice_id}.
Run: npm run aih:validate:work-plan -- ${slice_id} --plan-file ${rel_path}
Fix every reported error and re-run until exit 0 before PLAN_DONE ${slice_id}.
EOF
}

# Run work-planner every iteration; plan is ephemeral — implementer reads generated/runs/<run-id>-work-plan.md (same ralph-once).
# Returns 0 when a validated plan exists at generated/runs/<run-id>-work-plan.md.
run_work_plan_gate() {
  local slice_id="$1"
  local run_id="$2"
  local max_retries attempt plan_file plan_agent_out plan_agent_status=0
  local plan_agent_text plan_model plan_prompt plan_full_prompt
  local timeout_ms reason finalize_status=0
  local prior_errexit=0

  if [[ $- == *e* ]]; then prior_errexit=1; fi
  set +e

  plan_file="$(work_plan_run_abs "$run_id")"
  mkdir -p "$(dirname "$plan_file")"
  max_retries="$(work_plan_gate_max_retries)"
  attempt=0

  while true; do
    attempt=$((attempt + 1))
    if [[ "$attempt" -gt "$max_retries" ]]; then
      record_iteration_failure "$slice_id" "gate_failed" "plan_validation_failed" \
        "Work planner failed after ${max_retries} attempt(s) — see state/plan-validation-feedback/${slice_id}.txt"
      aih_err "Work planner exhausted ${max_retries} retries for ${slice_id}"
      [[ "$prior_errexit" -eq 1 ]] && set -e
      return 1
    fi

    if [[ "$attempt" -gt 1 ]]; then
      aih_warn "Work planner retry ${attempt}/${max_retries} for ${slice_id} (same Ralph iteration)"
    fi

    if [[ "$attempt" -eq 1 ]]; then
      plan_agent_out="${RUNS_DIR}/${run_id}-plan-agent.txt"
    else
      plan_agent_out="${RUNS_DIR}/${run_id}-plan-agent-r${attempt}.txt"
    fi

    if [[ "${AIH_SKIP_AGENT:-}" == "1" ]]; then
      aih_warn "AIH_SKIP_AGENT=1 — skipping work-planner agent"
      if [[ ! -f "$plan_file" ]]; then
        record_iteration_failure "$slice_id" "gate_failed" "plan_artifact_missing" \
          "Ephemeral plan missing at $(work_plan_run_path "$run_id") — place plan before AIH_SKIP_AGENT=1"
        aih_err "Work plan missing (AIH_SKIP_AGENT=1 does not skip validation)"
        [[ "$prior_errexit" -eq 1 ]] && set -e
        return 1
      fi
      echo "PLAN_DONE ${slice_id}" > "$plan_agent_out"
    else
      require_agent
      plan_prompt="$(AIH_RUN_ID="$run_id" ./ai-harness/scripts/build-prompt.sh "$slice_id" work-planner)"
      plan_model="$(get_model default)"
      plan_rel_path="$(work_plan_run_path "$run_id")"
      plan_full_prompt="${plan_prompt}

## Harness reminder

Write the implementation plan markdown to exactly: \`${plan_file}\`
This file is ephemeral (generated/runs) — the implementer reads it with the Read tool; it is not committed.
Do not edit any other files.
Read that path back and confirm the file is non-empty before your final message.
Run \`npm run aih:validate:work-plan -- ${slice_id} --plan-file ${plan_rel_path}\` and fix every error until it exits 0 before PLAN_DONE.
After validation passes, end with exactly one line: PLAN_DONE ${slice_id}
"
      aih_step "Running work-planner (${AGENT_BIN}, model=${plan_model}, attempt=${attempt}/${max_retries})"
      aih_agent_begin "work-planner (${plan_model})"
      set +e
      agent_invoke_work_planner "$plan_model" "$plan_full_prompt" "$plan_agent_out"
      plan_agent_status=$?
      aih_agent_end "${plan_agent_status}"
    fi

    if [[ "${plan_agent_status:-0}" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
      timeout_ms="$(get_agent_timeout_ms "$LOOP_CONFIG")"
      record_iteration_failure "$slice_id" "gate_failed" "plan_agent_timeout" \
        "Work-planner agent timed out after ${timeout_ms}ms — see $(basename "$plan_agent_out")"
      aih_err "Work-planner agent timed out. See guardrails.md"
      [[ "$prior_errexit" -eq 1 ]] && set -e
      return 1
    fi

    plan_agent_text="$(cat "$plan_agent_out" 2>/dev/null || true)"
    if echo "$plan_agent_text" | grep -q "PLAN_BLOCKED"; then
      reason="$(echo "$plan_agent_text" | grep "PLAN_BLOCKED" | tail -1)"
      record_iteration_failure "$slice_id" "blocked" "plan_blocked" "$reason"
      aih_err "Work plan blocked. See guardrails.md"
      [[ "$prior_errexit" -eq 1 ]] && set -e
      return 1
    fi

    finalize_ephemeral_work_plan "$slice_id" "$plan_file"
    finalize_status=$?
    if [[ "$finalize_status" -ne 0 ]]; then
      aih_warn "Work plan validation failed (attempt ${attempt}/${max_retries})"
      continue
    fi

    if ! parse_plan_done_from_agent "$plan_agent_text" "$slice_id"; then
      aih_warn "Work-planner did not emit PLAN_DONE ${slice_id} in agent output (plan validated — continuing)"
    fi
    break
  done

  export AIH_WORK_PLAN_FILE="$plan_file"
  append_progress "$slice_id" "planner_ok" || true
  aih_ok "Work plan ready for ${slice_id} — proceeding to implementer in this iteration"
  [[ "$prior_errexit" -eq 1 ]] && set -e
  return 0
}

parse_plan_done_from_agent() {
  local agent_text="$1"
  local slice_id="$2"
  if echo "$agent_text" | grep -qF "PLAN_DONE ${slice_id}"; then
    return 0
  fi
  # Agent stream may split the signal across formatting; accept same-line variants.
  echo "$agent_text" | grep -qE "PLAN_DONE[[:space:]]+${slice_id}([[:space:]]|$)"
}

format_work_plan_block() {
  local slice_id="$1"
  local artifact_abs rel_path
  artifact_abs="$(resolve_work_plan_file_for_prompt 2>/dev/null || true)"
  [[ -n "$artifact_abs" && -f "$artifact_abs" ]] || return 0
  rel_path="${artifact_abs#${REPO_ROOT}/}"

  cat <<EOF
## Work plan (this iteration)

**Mandatory:** Read the full work plan with the editor **Read** tool before backlog, other docs, or code:

\`${rel_path}\`

Follow **Implementation sequence** in order. Mark each step \`- [x]\` in the plan file after its **Verify:** passes.
When **Prior gate failures** appear above, read **Prior gate failure remediation** in the plan first (if present).
Deviate only per out-of-plan protocol in the implementer prompt.
EOF
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

playwright_regression_gate_enabled() {
  jq -r '.playwrightRegressionGate.enabled // true' "$LOOP_CONFIG"
}

slice_requires_playwright_regression_gate() {
  local slice_id="${1:-}"
  [[ -n "$slice_id" ]] || return 1
  [[ "$(playwright_regression_gate_enabled)" == "true" ]] || return 1
  slice_requires_browser_test "$slice_id"
}

integration_gate_enabled() {
  jq -r '.integrationGate.enabled // false' "$LOOP_CONFIG" 2>/dev/null
}

slice_in_integration_gate_block_list() {
  local slice_id="$1"
  jq -e --arg id "$slice_id" '.integrationGate.blockBrowserTestForSlices[]? | select(. == $id)' "$LOOP_CONFIG" >/dev/null 2>&1
}

integration_gate_requires_verify() {
  jq -r '.integrationGate.requireVerifyIntegrationPass // false' "$LOOP_CONFIG" 2>/dev/null
}

next_pending_phase4_slice_id() {
  jq -r '
    [.slices[]?
      | select(.passes == false)
      | select((.phase // 0) >= 4)
    ]
    | sort_by(.priority // 999)
    | .[0].id // empty
  ' "$BACKLOG" 2>/dev/null
}

handle_integration_gate_browser_block() {
  local slice_id="$1"
  local run_id="$2"
  local next_slice reason report
  next_slice="$(next_pending_phase4_slice_id)"
  reason="integration_debt_pending — complete integration wiring (AppModule, migrate/seed, fixtures) before browser test on ${slice_id}"
  report="$(jq -n \
    --arg slice "$slice_id" \
    --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg reason "$reason" \
    --arg nextSlice "${next_slice:-}" \
    '{
      slice: $slice,
      timestamp: $ts,
      pass: false,
      skipped: false,
      reason: $reason,
      integrationGateBlocked: true,
      focusNextSlice: (if $nextSlice == "" then null else $nextSlice end)
    }')"
  write_run_report "${run_id}-browser-test.json" "$report"
  if [[ -n "$next_slice" ]]; then
    if [[ "$(jq -r '.integrationGate.autoFocusNextPhase4Slice // false' "$LOOP_CONFIG")" == "true" ]]; then
      set_loop_slice_override "$next_slice" "$reason" "integration-gate"
      aih_warn "Integration gate blocked browser test — next iteration focused on ${next_slice}"
    fi
  fi
  record_iteration_failure "$slice_id" "blocked" "integration_debt_pending" "$reason"
}

integration_gate_blocks_browser_test() {
  local slice_id="$1"
  [[ "$(integration_gate_enabled)" == "true" ]] || return 1
  slice_in_integration_gate_block_list "$slice_id" || return 1
  [[ "$(integration_gate_requires_verify)" == "true" ]] || return 1
  set +e
  ./ai-harness/scripts/verify-integration.sh --check all >/dev/null 2>&1
  local status=$?
  set -e
  [[ "$status" -ne 0 ]]
}

browser_test_collect_all_failures() {
  jq -r '.browserTest.collectAllFailures // true' "$LOOP_CONFIG"
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

# Read-only reviewer: prompt forbids edits/shell/tests. NOT --mode plan —
# plan mode routes the agent's verdict into a createPlan artifact, which the
# stream adapter never captures to the outfile, so the REVIEW_PASS/REVIEW_FAIL
# marker is lost and the harness records a false failure.
agent_invoke_review() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args fmt
  args=(-p --force --trust --model "$model")
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

git_path_is_ignored() {
  local rel="$1"
  [[ -n "$rel" ]] || return 1
  git check-ignore -q -- "$rel" 2>/dev/null
}

# Tracked Playwright run artifacts that MCP/CLI mutate and break the scope gate.
playwright_scope_artifact_paths() {
  printf '%s\n' \
    "tests/playwright-ui/test-results/.last-run.json" \
    "tests/playwright-ui/playwright-report/index.html"
}

restore_playwright_scope_artifacts() {
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    return 0
  fi
  local rel restored=0
  while IFS= read -r rel; do
    [[ -z "$rel" ]] || continue
    if git_path_has_changes "$rel"; then
      git restore -- "$rel" 2>/dev/null || true
      restored=$((restored + 1))
    fi
  done < <(playwright_scope_artifact_paths)
  if [[ "$restored" -gt 0 ]]; then
    aih_warn "Restored ${restored} tracked Playwright artifact(s) before scope gate"
  fi
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
    if git_path_is_ignored "$rel"; then
      continue
    fi
    if git_path_has_changes "$rel"; then
      to_add+=("$rel")
    fi
  done

  [[ ${#to_add[@]} -gt 0 ]] || return 0
  git add -- "${to_add[@]}" 2>/dev/null || true
  # Pass an explicit pathspec so git commits ONLY the allowlisted paths (--only
  # mode) instead of sweeping up any other pre-staged/unreviewed changes.
  git commit -m "$message" --no-verify -- "${to_add[@]}" 2>/dev/null || true
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

manualsgen_owned_paths() {
  local item_id="$1"
  local output_path readme_path
  output_path="$(manual_artifact_path "$item_id")"
  readme_path="docs/user-manuals/README.md"
  printf '%s\n' \
    "$output_path" \
    "$readme_path" \
    "ai-harness/manuals-index.json" \
    "ai-harness/state/progress.md"
}

git_commit_manualsgen_pass() {
  local item_id="$1"
  local -a paths=()
  local path
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    paths+=("$path")
  done < <(manualsgen_owned_paths "$item_id")
  git_commit_allowlisted_paths "aih: generate user manual for ${item_id}" "${paths[@]}"
}

git_commit_browser_test_pass() {
  local slice_id="$1"
  local run_id="$2"
  local spec_path="${3:-}"
  local -a paths=()
  local path
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    paths+=("$path")
  done < <(browser_test_owned_paths "$slice_id" "$run_id" "$spec_path")
  if git_path_has_changes "ai-harness/whole-app-backlog.json"; then
    paths+=("ai-harness/whole-app-backlog.json")
  fi
  git_commit_allowlisted_paths "aih: browser test regression for ${slice_id}" "${paths[@]}"
}

finalize_browser_test_pass() {
  local slice_id="$1"
  local run_id="$2"
  local spec_path="${3:-}"
  local ref validate_out
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    if git_path_has_changes "$(test_case_artifact_path "$ref")"; then
      set +e
      validate_out="$(./ai-harness/scripts/validate-test-cases.sh "$ref" 2>&1)"
      local validate_status=$?
      set -e
      if [[ "$validate_status" -ne 0 ]]; then
        echo "$validate_out" >&2
        return 1
      fi
      ./ai-harness/scripts/sync-test-cases-to-backlog.sh "$ref"
    fi
  done < <(slice_product_item_refs "$slice_id" 2>/dev/null || true)
  git_commit_browser_test_pass "$slice_id" "$run_id" "$spec_path"
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

# True when a prior iteration left scope/checks/browser/review gate artifacts for this slice.
slice_has_prior_gate_failures() {
  local slice_id="$1"
  local kind
  for kind in scope checks browser-test review; do
    if find_latest_failed_run_id_for_slice "$slice_id" "$kind" >/dev/null 2>&1; then
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

browser_test_max_cases_per_batch() {
  if [[ -n "${AIH_BROWSER_TEST_MAX_CASES_PER_BATCH:-}" ]]; then
    echo "${AIH_BROWSER_TEST_MAX_CASES_PER_BATCH}"
    return 0
  fi
  jq -r '.browserTest.maxCasesPerBatch // 10' "$LOOP_CONFIG"
}

browser_test_batching_enabled() {
  local max
  max="$(browser_test_max_cases_per_batch)"
  [[ "$max" =~ ^[0-9]+$ ]] && [[ "$max" -gt 0 ]]
}

# Runnable browser case IDs for a slice, sorted P0→P3 (stable within priority).
list_runnable_browser_case_ids_for_slice() {
  local slice_id="$1"
  load_test_cases_json_for_slice "$slice_id" | jq -r '
    def prio_rank($p):
      if $p == "P0" then 0
      elif $p == "P1" then 1
      elif $p == "P2" then 2
      elif $p == "P3" then 3
      else 4
      end;
    [.cases[]? | select(.layer == "browser") | select((.harnessSkip // "") == "")]
    | sort_by(prio_rank(.priority), .id)
    | .[].id
  ' 2>/dev/null
}

# Split newline-separated case IDs into batches of at most max_per_batch.
# Prints one JSON array per batch line.
split_case_ids_into_batches() {
  local max_per_batch="$1"
  shift
  local ids_json
  ids_json="$(printf '%s\n' "$@" | jq -R . | jq -s 'map(select(. != ""))')"
  jq -c --argjson max "$max_per_batch" '
    def chunk($n):
      if length == 0 then []
      elif length <= $n then [.]
      else [.[0:$n]] + (.[$n:] | chunk($n))
      end;
    chunk($max) | .[]
  ' <<< "$ids_json"
}

# Ensure every expected case ID has PASS or SKIP (not FAIL or missing) in output.
validate_batch_case_results() {
  local text_file="$1"
  shift
  local case_id
  [[ -f "$text_file" ]] || return 1
  [[ $# -gt 0 ]] || return 0
  if ! browser_case_ids_still_failing_in_output "$text_file" "$@"; then
    return 1
  fi
  for case_id in "$@"; do
    if ! grep -qE "${case_id}:[[:space:]]*(PASS|SKIP)" "$text_file" 2>/dev/null; then
      return 1
    fi
  done
  return 0
}

browser_output_has_batch_pass_signal() {
  local text_file="$1"
  [[ -f "$text_file" ]] || return 1
  grep -q 'BROWSER_TEST_BATCH_PASS' "$text_file" 2>/dev/null
}

extract_passed_browser_case_ids_from_output() {
  local text_file="$1"
  [[ -f "$text_file" ]] || return 1
  grep -oE 'TC-[A-Z0-9][A-Z0-9-]*:[[:space:]]*PASS' "$text_file" 2>/dev/null \
    | sed -E 's/:[[:space:]]*PASS$//' \
    | sort -u
}

format_prior_batch_summary_block() {
  local -a outfile_paths=("$@")
  local path cid block=""
  for path in "${outfile_paths[@]}"; do
    [[ -f "$path" ]] || continue
    while IFS= read -r cid; do
      [[ -z "$cid" ]] && continue
      block+="- ${cid}: PASS"$'\n'
    done < <(extract_passed_browser_case_ids_from_output "$path" 2>/dev/null || true)
  done
  if [[ -n "$block" ]]; then
    printf '%s\n' "## Prior batch results (functional cases already verified — do not re-run)

The harness executed these browser cases in earlier batches. Use this list to know which screens/states were exercised.

${block}"
  fi
}

append_batch_phase_result() {
  local phases_json="$1"
  local phase="$2"
  local pass="$3"
  local batch_index="$4"
  local batch_total="$5"
  local prior_run_id="${6:-}"
  local case_ids_json="${7:-[]}"
  jq -n \
    --argjson phases "$phases_json" \
    --arg name "$phase" \
    --argjson pass "$pass" \
    --argjson batchIndex "$batch_index" \
    --argjson batchTotal "$batch_total" \
    --arg prior "$prior_run_id" \
    --argjson caseIds "$case_ids_json" \
    '$phases + [{
      name: $name,
      pass: $pass,
      batchIndex: $batchIndex,
      batchTotal: $batchTotal,
      priorRunId: (if $prior == "" then null else $prior end),
      caseIds: (if ($caseIds | length) == 0 then null else $caseIds end)
    }]'
}

common_ui_ux_suite_enabled() {
  jq -r '.browserTest.commonUiUxSuite.enabled // true' "$LOOP_CONFIG"
}

common_ui_ux_suite_path() {
  local rel
  rel="$(jq -r '.browserTest.commonUiUxSuite.path // empty' "$LOOP_CONFIG" 2>/dev/null || true)"
  if [[ -n "$rel" ]]; then
    echo "${REPO_ROOT}/${rel}"
  else
    echo "$COMMON_UI_UX_SUITE_DEFAULT"
  fi
}

common_ui_ux_suite_blocking_priorities_json() {
  jq -c '.browserTest.commonUiUxSuite.blockingPriorities // ["P0","P1"]' "$LOOP_CONFIG" 2>/dev/null || echo '["P0","P1"]'
}

load_common_ui_ux_suite() {
  local suite
  [[ "$(common_ui_ux_suite_enabled)" == "true" ]] || return 1
  suite="$(common_ui_ux_suite_path)"
  [[ -f "$suite" ]] || return 1
  jq empty "$suite" 2>/dev/null || return 1
  cat "$suite"
}

format_common_ui_ux_suite_block() {
  local suite
  suite="$(common_ui_ux_suite_path)"
  [[ -f "$suite" ]] || return 1
  jq -r '
    .cases[]?
    | "- **\(.id)** [\(.priority)/\(.technique)]: \(.title)"
      + (if .appliesTo then "\n  Applies to: \(.appliesTo)" else "" end)
      + (if (.preconditions // []) | length > 0 then "\n  Preconditions: \(.preconditions | join("; "))" else "" end)
      + "\n  Steps: \(.steps | join(" → "))\n  Expected: \(.expected)"
  ' "$suite" 2>/dev/null
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
  jq '{slice, violations, hint: "Revert unrelated edits, or add justified paths to scopeExtensions (with reason), completionArtifacts, or testRequirements in whole-app-backlog.json — see implementer prompt Supportive out-of-scope changes and guardrails.md."}' \
    "$json_file" 2>/dev/null | head -c "$max_chars"
}

integration_failure_policy_investigate() {
  jq -r '.computationalChecks.integrationFailurePolicy.investigateOnFailure // false' "$LOOP_CONFIG"
}

integration_failure_auto_reopen_owner() {
  jq -r '.computationalChecks.integrationFailurePolicy.autoReopenOwnerSlice // false' "$LOOP_CONFIG"
}

integration_failure_auto_focus_owner() {
  jq -r '.computationalChecks.integrationFailurePolicy.autoFocusOwnerSlice // false' "$LOOP_CONFIG"
}

checks_run_has_integration_failure() {
  local run_id="$1"
  local json_file="${RUNS_DIR}/${run_id}-checks.json"
  [[ -f "$json_file" ]] || return 1
  jq -e '.failures[]? | select(.script == "test:integration")' "$json_file" >/dev/null 2>&1
}

get_integration_check_log_path() {
  local run_id="$1"
  printf '%s/%s-check-test-integration.log' "$RUNS_DIR" "$run_id"
}

run_isolated_integration_file() {
  local test_path="$1"
  local test_rel="$test_path"
  if [[ "$test_rel" == apps/api/* ]]; then
    test_rel="${test_rel#apps/api/}"
  fi
  [[ -n "$test_rel" ]] || return 1

  if ! prepare_test_stack_for_script "test:integration"; then
    return 1
  fi
  export_test_stack_env

  local api_dir="${REPO_ROOT}/apps/api"
  [[ -d "$api_dir" ]] || return 1

  set +e
  (
    cd "$api_dir"
    node --import tsx --test --test-concurrency=1 --test-reporter=spec "$test_rel"
  )
  local status=$?
  set -e
  return "$status"
}

run_integration_failure_triage() {
  local current_slice="$1"
  local run_id="$2"
  local log_file triage_file failing_path isolated_status=1 isolated_attempted="false"

  [[ "$(integration_failure_policy_investigate)" == "true" ]] || return 1
  checks_run_has_integration_failure "$run_id" || return 1

  log_file="$(get_integration_check_log_path "$run_id")"
  [[ -f "$log_file" ]] || return 1
  [[ -f "$INTEGRATION_FAILURE_TRIAGE_JS" ]] || return 1

  failing_path="$(node -e "
    const fs = require('node:fs');
    const m = require('${CHECK_LOG_EXCERPT_JS}');
    const text = fs.readFileSync(process.argv[1], 'utf8');
    const excerpt = m.extractCheckLogFailureExcerpt(text, 12000);
    const paths = m.extractFailingTestPaths(excerpt);
    console.log(paths[0] || '');
  " "$log_file" 2>/dev/null || true)"

  if [[ -n "$failing_path" ]]; then
    isolated_attempted="true"
    aih_info "integration triage: running isolated suite for ${failing_path}"
    set +e
    run_isolated_integration_file "$failing_path"
    isolated_status=$?
    set -e
  fi

  triage_file="${RUNS_DIR}/${run_id}-integration-triage.json"
  if ! node "$INTEGRATION_FAILURE_TRIAGE_JS" triage \
    --current-slice "$current_slice" \
    --log "$log_file" \
    --backlog "$BACKLOG" \
    --isolated-exit-code "$isolated_status" \
    --isolated-run-attempted "$isolated_attempted" \
    --output "$triage_file" 2>/dev/null; then
    return 1
  fi
  [[ -f "$triage_file" ]] || return 1
  printf '%s' "$triage_file"
}

merge_triage_into_checks_report() {
  local run_id="$1"
  local triage_file="$2"
  local checks_file="${RUNS_DIR}/${run_id}-checks.json"
  local tmp
  [[ -f "$checks_file" && -f "$triage_file" ]] || return 1
  tmp="$(mktemp)"
  jq --slurpfile triage "$triage_file" '. + {triage: $triage[0]}' "$checks_file" > "$tmp" && mv "$tmp" "$checks_file"
}

format_integration_failure_guardrail_line() {
  local triage_file="$1"
  local classification owner cases
  [[ -f "$triage_file" ]] || return 1
  classification="$(jq -r '.classification // empty' "$triage_file")"
  owner="$(jq -r '.ownerSlice // empty' "$triage_file")"
  cases="$(jq -r '(.failingCaseIds // []) | join(", ")' "$triage_file")"

  if [[ "$classification" == "crossSuiteFlake" && -n "$owner" ]]; then
    printf '%s' "${cases} cross-suite flake — owner ${owner} reopened; fix shared fixture pollution (afterEach restore / dedicated section); bare re-run is not a fix"
    return 0
  fi
  if [[ "$classification" == "reproducible" && -n "$owner" ]]; then
    printf '%s' "${cases} reproducible integration failure — owner ${owner} must fix; bare re-run is not a fix"
    return 0
  fi
  if [[ "$classification" == "infrastructure" ]]; then
    printf '%s' "integration infrastructure failure — reset test stack (npm run aih:test:stack:reset) before retry"
    return 0
  fi
  return 1
}

apply_integration_failure_routing() {
  local current_slice="$1"
  local triage_file="$2"
  local classification owner cases reason

  [[ -f "$triage_file" ]] || return 0
  classification="$(jq -r '.classification // empty' "$triage_file")"
  owner="$(jq -r '.ownerSlice // empty' "$triage_file")"
  cases="$(jq -r '(.failingCaseIds // []) | join(", ")' "$triage_file")"

  [[ -n "$owner" && "$owner" != "$current_slice" ]] || return 0
  [[ "$classification" == "crossSuiteFlake" || "$classification" == "reproducible" ]] || return 0

  reason="integration ${classification}: ${cases:-unknown failure} — fix parallel test isolation / root cause in owning tests"

  if [[ "$(integration_failure_auto_reopen_owner)" == "true" ]]; then
    mark_slice_reopened "$owner" "$reason" "harness" "integration_triage" "$current_slice"
    aih_warn "Integration triage reopened owner slice: ${owner}"
  fi

  if [[ "$(integration_failure_auto_focus_owner)" == "true" ]]; then
    set_loop_slice_override "$owner" "integration flake investigation: ${cases:-see triage}" "ralph-once"
    aih_warn "Next iteration focused on owner slice: ${owner}"
  fi
}

format_integration_triage_investigation_block() {
  local run_id="$1"
  local triage_file="${RUNS_DIR}/${run_id}-integration-triage.json"
  local classification owner cases paths isolated_pass current focus_note=""
  [[ -f "$triage_file" ]] || return 0

  classification="$(jq -r '.classification // empty' "$triage_file")"
  owner="$(jq -r '.ownerSlice // empty' "$triage_file")"
  cases="$(jq -r '(.failingCaseIds // []) | join(", ")' "$triage_file")"
  paths="$(jq -r '(.failingTestPaths // []) | join(", ")' "$triage_file")"
  isolated_pass="$(jq -r '.isolatedRunPass // false' "$triage_file")"
  current="$(jq -r '.currentSlice // empty' "$triage_file")"

  if [[ -n "$owner" && "$owner" != "$current" ]]; then
    focus_note=" (harness has focused \`${owner}\` for the next iteration when auto-routing fired)"
  fi

  cat <<EOF
### Integration failure investigation (mandatory)

Do **not** resolve this by re-running \`npm run aih:check\` until you apply a code fix.

1. Read \`${run_id}-integration-triage.json\` and log excerpts below.
2. Run isolated suite: \`npm run aih:run-check -- test:integration -w {{WORKSPACE_NAME}}api -- <failing-file>\`
3. Classification: **${classification}**$([[ "$isolated_pass" == "true" ]] && echo " (isolated run passed)") — failing case(s): ${cases:-unknown}; file(s): ${paths:-see log}
4. If cross-suite pollution → fix isolation in **owner slice** \`${owner:-unknown}\` (see test-failure-triage.md § Integration flake patterns).
5. If out of scope for \`${current}\` → signal \`SLICE_DEFER ${owner} <reason>\`${focus_note}.
6. Document the **root-cause fix** in progress.md — "passes on re-run" alone is not acceptable.

EOF
}

build_slice_prior_gate_failures_block() {
  local slice_id="$1"
  local audience="${2:-implementer}"
  local block sections="" excerpt_block="" fix_order="" fix_order_num=0
  local scope_run="" checks_run="" browser_run="" review_run=""

  if scope_run="$(find_latest_failed_run_id_for_slice "$slice_id" scope)"; then
    block="$(summarize_scope_failures "$scope_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      fix_order_num=$((fix_order_num + 1))
      fix_order="${fix_order}${fix_order_num}. Scope gate — revert or declare out-of-scope paths; verify with \`npm run aih:scope -- ${slice_id}\`
"
      sections="${sections}### Scope gate failures (\`${scope_run}\`)

Fix every out-of-scope path below before signaling \`SLICE_DONE\`. Either revert unrelated edits, or add each justified path to this slice's \`scopeExtensions\` (with reason) or \`completionArtifacts\` / \`testRequirements\` in \`whole-app-backlog.json\`.

**Targeted verify:** \`npm run aih:scope -- ${slice_id}\`

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
      fix_order_num=$((fix_order_num + 1))
      fix_order="${fix_order}${fix_order_num}. Computational checks — fix each failed script; verify with \`npm run aih:run-check -- <failed-script>\`
"
      sections="${sections}### Computational checks failures (\`${checks_run}\`)

Fix every item below before signaling \`SLICE_DONE\`. **Read the log excerpts** — they contain assertion errors and test case ids the JSON summary omits.

**Targeted verify:** \`npm run aih:run-check -- <failed-script>\` (or isolated integration pattern from triage block)

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
      triage_block="$(format_integration_triage_investigation_block "$checks_run" 2>/dev/null || true)"
      if [[ -n "$triage_block" ]]; then
        sections="${sections}${triage_block}"
      elif checks_run_has_integration_failure "$checks_run" 2>/dev/null; then
        sections="${sections}### Integration failure investigation (mandatory)

Do **not** resolve integration gate failures by bare re-run of \`npm run aih:check\`. Fix root cause or signal \`SLICE_DEFER <owner-slice-id> <reason>\` per test-failure-triage.md.

"
      fi
    fi
  fi

  if browser_run="$(find_latest_failed_run_id_for_slice "$slice_id" browser-test)"; then
    block="$(summarize_browser_test_failures "$browser_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      fix_order_num=$((fix_order_num + 1))
      fix_order="${fix_order}${fix_order_num}. Browser test — fix failed \`TC-*\` / P0/P1 \`UX-*\` cases; re-exercise only listed failures
"
      sections="${sections}### Browser test failures (\`${browser_run}\`)

Fix only the failed cases below before signaling \`SLICE_DONE\`.

**Targeted verify:** re-exercise only the failed cases/screens listed below (Playwright MCP or cursor-ide-browser)

\`\`\`
${block}
\`\`\`

"
    fi
  fi

  if review_run="$(find_latest_failed_run_id_for_slice "$slice_id" review)"; then
    block="$(summarize_review_failures "$review_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      fix_order_num=$((fix_order_num + 1))
      fix_order="${fix_order}${fix_order_num}. AI code review — resolve each listed blocker in changed files
"
      sections="${sections}### AI code review blockers (\`${review_run}\`)

Resolve the blockers below before signaling \`SLICE_DONE\`.

**Targeted verify:** confirm each listed blocker is resolved in the changed files (no full re-review needed)

\`\`\`
${block}
\`\`\`

"
    fi
  fi

  [[ -n "$sections" ]] || return 0

  case "$audience" in
    planner)
      cat <<EOF
## Prior gate failures — replan context

This slice failed an implementation gate on a previous iteration. **Regenerate** the plan for this iteration from current state — preserve acceptance/testing/files sections where still accurate when failures are narrow; when **Prior gate failures** are listed below, remediation comes first.

**Required plan changes when failures are listed below:**

1. Add **## Prior gate failure remediation** immediately after the \`# Plan:\` title (before **Acceptance coverage**).
2. Map **every** failure category below to concrete fix steps: files to touch, root cause, and targeted verify command.
3. Rewrite **Implementation sequence** so numbered steps **start** with those remediation fixes (gate order below) before any remaining build work.

**Gate fix order:**

${fix_order}
${sections}
EOF
      ;;
    *)
      cat <<EOF
## Prior gate failures — fix these before anything else

This slice failed on a previous iteration. **Do not** run full checks or re-read all docs first.
Fix every item below in gate order, using targeted verification after each category.
When the approved plan includes **## Prior gate failure remediation**, follow that section first — it should mirror the failures below.

**Fix order:**

${fix_order}
${sections}
EOF
      ;;
  esac
}

build_implementer_prior_gate_feedback() {
  build_slice_prior_gate_failures_block "$1" implementer
}

build_planner_prior_gate_feedback() {
  build_slice_prior_gate_failures_block "$1" planner
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

test_stack_reset_between_scripts() {
  jq -r '.computationalChecks.runtimeValidation.testStack.resetBetweenScripts // false' "$LOOP_CONFIG"
}

# Tear down/reuse the ephemeral test stack, then export connection env vars.
# With resetBetweenScripts=false, one check run can reuse the primed stack for e2e after integration.
prepare_test_stack_for_script() {
  local script="${1:-}"
  script_needs_test_stack "$script" || return 0
  if ! test_stack_configured; then
    return 0
  fi
  if [[ "$(test_stack_reset_between_scripts)" == "false" && "${AIH_TEST_STACK_PRIMED:-0}" == "1" ]]; then
    if wait_test_stack_healthy; then
      aih_info "    reusing primed test stack before ${script} (resetBetweenScripts=false)"
      export_test_stack_env
      return 0
    fi
    aih_info "    primed test stack unhealthy; resetting before ${script}"
  fi
  aih_info "    resetting test stack before ${script} (via $(test_stack_script) reset, AIH_TEST_STACK_RESET=${AIH_TEST_STACK_RESET:-1})"
  if ! reset_test_stack_if_needed; then
    aih_err "test stack reset failed before ${script}"
    return 1
  fi
  export AIH_TEST_STACK_PRIMED=1
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
