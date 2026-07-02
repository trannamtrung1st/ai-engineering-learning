#!/usr/bin/env bash
# Shared generator utilities — independent from ai-harness.
set -euo pipefail

# shellcheck source=console.sh
source "$(dirname "${BASH_SOURCE[0]}")/console.sh"
# shellcheck source=product-meta.sh
source "$(dirname "${BASH_SOURCE[0]}")/product-meta.sh"

GEN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEN_SCRIPTS_DIR="${GEN_ROOT}/scripts"
if [[ -n "${GEN_REPO_ROOT:-}" ]]; then
  REPO_ROOT="$(cd "${GEN_REPO_ROOT}" && pwd)"
else
  REPO_ROOT="$(cd "${GEN_ROOT}/.." && pwd)"
fi

STEPS_BACKLOG="${GEN_ROOT}/steps-backlog.json"
LOOP_CONFIG="${GEN_ROOT}/workflows/gen-loop.json"
MODELS_CONFIG="${GEN_ROOT}/config/models.json"
DOC_OUTLINES="${GEN_ROOT}/config/doc-outlines.json"
GEN_STATE_DIR="${GEN_ROOT}/state"
RUNS_DIR="${GEN_ROOT}/generated/runs"
INITIAL_IDEA="${REPO_ROOT}/docs/initial-idea.md"
PRODUCT_META_FILE="${REPO_ROOT}/docs/product-meta.json"
TEMPLATES_DIR="${GEN_ROOT}/templates"

export GEN_ROOT GEN_SCRIPTS_DIR REPO_ROOT STEPS_BACKLOG LOOP_CONFIG MODELS_CONFIG DOC_OUTLINES GEN_STATE_DIR RUNS_DIR INITIAL_IDEA PRODUCT_META_FILE TEMPLATES_DIR

AGENT_TIMEOUT_EXIT=124
AGENT_TIMEOUT_DEFAULT_MS=3600000
AGENT_IDLE_TIMEOUT_DEFAULT_MS=300000
AGENT_SIGNAL_GRACE_DEFAULT_MS=15000
AGENT_RESULT_GRACE_DEFAULT_MS=5000

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    gen_err "required command not found: $cmd"
    exit 1
  fi
}

require_gen_deps() {
  require_cmd jq
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

require_agent() {
  AGENT_BIN="$(resolve_agent_bin)"
  if [[ -z "$AGENT_BIN" ]]; then
    gen_err "Cursor CLI not found. Install: curl https://cursor.com/install -fsS | bash"
    gen_err "Then authenticate: agent login"
    exit 1
  fi
  export AGENT_BIN
}

get_model() {
  local key="${1:-default}"
  if [[ "$key" == "default" && -n "${GEN_MODEL:-}" ]]; then
    echo "$GEN_MODEL"
    return
  fi
  if [[ "$key" == "reviewer" && -n "${GEN_REVIEWER_MODEL:-}" ]]; then
    echo "$GEN_REVIEWER_MODEL"
    return
  fi
  jq -r --arg k "$key" '.[$k] // .default' "$MODELS_CONFIG"
}

get_agent_timeout_ms() {
  local config="${1:-$LOOP_CONFIG}"
  if [[ -n "${GEN_AGENT_TIMEOUT_MS:-}" ]]; then
    echo "$GEN_AGENT_TIMEOUT_MS"
    return
  fi
  jq -r ".agent.timeoutMs // ${AGENT_TIMEOUT_DEFAULT_MS}" "$config"
}

get_agent_idle_timeout_ms() {
  local config="${1:-$LOOP_CONFIG}"
  if [[ -n "${GEN_AGENT_IDLE_TIMEOUT_MS:-}" ]]; then
    echo "$GEN_AGENT_IDLE_TIMEOUT_MS"
    return
  fi
  jq -r ".agent.idleTimeoutMs // ${AGENT_IDLE_TIMEOUT_DEFAULT_MS}" "$config"
}

get_agent_signal_grace_ms() {
  local config="${1:-$LOOP_CONFIG}"
  if [[ -n "${GEN_AGENT_SIGNAL_GRACE_MS:-}" ]]; then
    echo "$GEN_AGENT_SIGNAL_GRACE_MS"
    return
  fi
  jq -r ".agent.signalGraceMs // ${AGENT_SIGNAL_GRACE_DEFAULT_MS}" "$config"
}

get_agent_result_grace_ms() {
  local config="${1:-$LOOP_CONFIG}"
  if [[ -n "${GEN_AGENT_RESULT_GRACE_MS:-}" ]]; then
    echo "$GEN_AGENT_RESULT_GRACE_MS"
    return
  fi
  jq -r ".agent.resultGraceMs // ${AGENT_RESULT_GRACE_DEFAULT_MS}" "$config"
}

agent_completion_signals_csv() {
  local config="${1:-$LOOP_CONFIG}"
  jq -r '[.signals[]? // empty] | unique | join(",")' "$config"
}

agent_stream_enabled() {
  [[ "${GEN_STREAM_AGENT:-1}" != "0" ]]
}

run_agent_uses_stream_json() {
  local arg
  for arg in "$@"; do
    [[ "$arg" == "stream-json" ]] && return 0
  done
  return 1
}

agent_verbose_enabled() {
  [[ "${GEN_AGENT_VERBOSE:-1}" == "1" ]]
}

agent_output_format_args() {
  if agent_stream_enabled; then
    echo '--output-format stream-json --stream-partial-output'
  else
    echo '--output-format text'
  fi
}

agent_timeout_message() {
  local timeout_ms="$1"
  local timeout_min=$(( timeout_ms / 60000 ))
  echo "ERROR: Agent timed out after ${timeout_ms}ms (${timeout_min}m)"
}

run_command_with_timeout_ms() {
  local timeout_ms="$1"
  shift
  local deadline=$(( $(date +%s) * 1000 + timeout_ms ))
  local cmd_pid

  "$@" &
  cmd_pid=$!

  while kill -0 "$cmd_pid" 2>/dev/null; do
    if (( $(date +%s) * 1000 >= deadline )); then
      gen_err "Agent timed out after ${timeout_ms}ms"
      kill -TERM "$cmd_pid" 2>/dev/null || true
      sleep 2
      kill -KILL "$cmd_pid" 2>/dev/null || true
      wait "$cmd_pid" 2>/dev/null || true
      return "$AGENT_TIMEOUT_EXIT"
    fi
    sleep 2
  done

  wait "$cmd_pid"
}

run_agent_with_timeout_ms() {
  local timeout_ms="$1"
  local outfile="$2"
  shift 2
  local status timeout_msg

  if [[ -n "$outfile" ]] && agent_stream_enabled && run_agent_uses_stream_json "$@"; then
    require_cmd node
    local idle_ms signal_grace_ms result_grace_ms signals_csv
    local -a stream_cmd
    idle_ms="$(get_agent_idle_timeout_ms)"
    signal_grace_ms="$(get_agent_signal_grace_ms)"
    result_grace_ms="$(get_agent_result_grace_ms)"
    signals_csv="$(agent_completion_signals_csv)"
    stream_cmd=(node "${TEMPLATES_DIR}/ai-harness/scripts/lib/stream-agent-output.js" \
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
    set +e
    run_command_with_timeout_ms "$timeout_ms" "$@" | tee "$outfile"
    status=${PIPESTATUS[0]}
    set -e
    return "$status"
  fi

  run_command_with_timeout_ms "$timeout_ms" "$@"
}

agent_invoke() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local timeout_ms
  local -a args fmt
  args=(-p --force --model "$model")
  read -ra fmt <<< "$(agent_output_format_args)"
  args+=("${fmt[@]}")
  timeout_ms="$(get_agent_timeout_ms)"
  run_agent_with_timeout_ms "$timeout_ms" "$outfile" "$AGENT_BIN" "${args[@]}" "$prompt"
}

agent_invoke_review() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local timeout_ms
  local -a args fmt
  args=(-p --force --trust --model "$model" --mode plan)
  read -ra fmt <<< "$(agent_output_format_args)"
  args+=("${fmt[@]}")
  timeout_ms="$(get_agent_timeout_ms)"
  run_agent_with_timeout_ms "$timeout_ms" "$outfile" "$AGENT_BIN" "${args[@]}" "$prompt"
}

run_id() {
  date -u +"%Y%m%dT%H%M%SZ"
}

ensure_runs_dir() {
  mkdir -p "$RUNS_DIR"
}

gen_apply_enabled() {
  [[ "${GEN_APPLY:-}" == "1" || "${GEN_APPLY:-}" == "true" ]]
}

assert_can_write_outputs() {
  if ! gen_apply_enabled; then
    gen_err "GEN_APPLY is not set — generator runs in dry-run mode and will not write repo outputs."
    gen_err "Set GEN_APPLY=1 to write docs/ and ai-harness/ at repo root."
    exit 1
  fi
}

# Block overwriting an existing harness only when (re)scaffolding before the loop has started phase 4.
assert_safe_to_scaffold_harness() {
  assert_can_write_outputs
  if [[ -f "${REPO_ROOT}/ai-harness/whole-app-backlog.json" && "${GEN_FORCE:-}" != "1" ]]; then
    gen_err "ai-harness/whole-app-backlog.json already exists. Set GEN_FORCE=1 to overwrite."
    exit 1
  fi
}

generator_resume_in_progress() {
  [[ -f "$STEPS_BACKLOG" ]] || return 1
  if all_steps_pass; then
    return 1
  fi
  local scaffold_passed
  scaffold_passed="$(jq -r '.steps[] | select(.id == "harness-scaffold") | .passes // false' "$STEPS_BACKLOG")"
  [[ "$scaffold_passed" == "true" ]]
}

all_steps_pass() {
  local pending
  pending="$(jq '[.steps[] | select(.passes == false)] | length' "$STEPS_BACKLOG")"
  [[ "$pending" -eq 0 ]]
}

pick_next_step_id() {
  jq -r '
    [.steps[] | select(.passes == false)]
    | sort_by(.priority)
    | .[0].id // empty
  ' "$STEPS_BACKLOG"
}

get_step_field() {
  local step_id="$1"
  local field="$2"
  jq -r --arg id "$step_id" --arg f "$field" '
    .steps[] | select(.id == $id) | .[$f]
  ' "$STEPS_BACKLOG"
}

get_step_json() {
  local step_id="$1"
  jq -c --arg id "$step_id" '.steps[] | select(.id == $id)' "$STEPS_BACKLOG"
}

mark_step_passed() {
  local step_id="$1"
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$step_id" '
    .steps |= map(if .id == $id then .passes = true else . end)
  ' "$STEPS_BACKLOG" > "$tmp"
  mv "$tmp" "$STEPS_BACKLOG"
}

append_progress() {
  local step_id="$1"
  local status="$2"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "- [${ts}] **${step_id}** — ${status}" >> "${GEN_STATE_DIR}/progress.md"
}

append_guardrail() {
  local step_id="$1"
  local message="$2"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  {
    echo ""
    echo "## ${step_id} (${ts})"
    echo ""
    echo "$message"
  } >> "${GEN_STATE_DIR}/guardrails.md"
}

step_outputs() {
  local step_id="$1"
  get_step_json "$step_id" | jq -r '.outputs[]? // empty'
}

step_context_docs() {
  local step_id="$1"
  get_step_json "$step_id" | jq -r '.contextDocs[]? // empty'
}

step_validators() {
  local step_id="$1"
  get_step_json "$step_id" | jq -r '.validators[]? // empty'
}

step_is_gate() {
  local step_id="$1"
  [[ "$(get_step_field "$step_id" kind)" == "gate" ]]
}

step_agent() {
  local step_id="$1"
  get_step_field "$step_id" agent
}

print_gen_env() {
  local bin
  bin="$(resolve_agent_bin)"
  echo "$(gen_bold "$(gen_cyan "Generator")")"
  if [[ -n "$bin" ]]; then
    gen_kv "Agent" "$bin"
    gen_kv "Model" "$(get_model default)"
    gen_kv "Reviewer" "$(get_model reviewer)"
  else
    gen_kv "Agent" "not installed"
  fi
  gen_kv "Repo" "$REPO_ROOT"
  gen_kv "Apply" "${GEN_APPLY:-0} (GEN_FORCE=${GEN_FORCE:-0})"
}

resolve_repo_path() {
  local rel="$1"
  echo "${REPO_ROOT}/${rel}"
}

GATE_REPAIR_STATE="${GEN_STATE_DIR}/gate-repair-counts.json"

gate_recovery_enabled() {
  [[ "${GEN_SKIP_GATE_REPAIR:-}" == "1" ]] && return 1
  [[ "$(jq -r '.gateRecovery.enabled // true' "$LOOP_CONFIG")" == "true" ]]
}

gate_recovery_max_attempts() {
  jq -r '.gateRecovery.maxRepairAttemptsPerStep // 3' "$LOOP_CONFIG"
}

get_gate_repair_count() {
  local step_id="$1"
  if [[ ! -f "$GATE_REPAIR_STATE" ]]; then
    echo 0
    return
  fi
  jq -r --arg id "$step_id" '.[$id] // 0' "$GATE_REPAIR_STATE"
}

increment_gate_repair_count() {
  local step_id="$1"
  local tmp count
  count="$(get_gate_repair_count "$step_id")"
  count=$((count + 1))
  tmp="$(mktemp)"
  if [[ -f "$GATE_REPAIR_STATE" ]]; then
    jq --arg id "$step_id" --argjson n "$count" '.[$id] = $n' "$GATE_REPAIR_STATE" > "$tmp"
  else
    jq -n --arg id "$step_id" --argjson n "$count" '{($id): $n}' > "$tmp"
  fi
  mv "$tmp" "$GATE_REPAIR_STATE"
}

reset_gate_repair_count() {
  local step_id="$1"
  [[ ! -f "$GATE_REPAIR_STATE" ]] && return 0
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$step_id" 'del(.[$id])' "$GATE_REPAIR_STATE" > "$tmp"
  mv "$tmp" "$GATE_REPAIR_STATE"
}
