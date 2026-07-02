#!/usr/bin/env bash
# Run one root package.json script with harness timeout, live output, heartbeat, and log file.
# Use for ad-hoc agent self-checks (especially test:integration) to avoid silent hangs.
#
# Usage: run-logged-check.sh <npm-script> [--profile fast|full] [extra npm args...]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

SCRIPT=""
CHECK_PROFILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      CHECK_PROFILE="${2:?profile required}"
      shift 2
      ;;
    --profile=*)
      CHECK_PROFILE="${1#--profile=}"
      shift
      ;;
    *)
      if [[ -z "$SCRIPT" ]]; then
        SCRIPT="$1"
      fi
      shift
      ;;
  esac
done
SCRIPT="${SCRIPT:?npm script name required — e.g. test:integration}"
[[ -n "$CHECK_PROFILE" ]] && export AIH_CHECK_PROFILE="$CHECK_PROFILE"

require_harness_deps
ensure_runs_dir

cd "$REPO_ROOT"

if [[ ! -f package.json ]]; then
  echo "ERROR: package.json not found" >&2
  exit 1
fi
if ! jq -e --arg s "$SCRIPT" '.scripts[$s]' package.json >/dev/null 2>&1; then
  echo "ERROR: npm script not found in package.json: ${SCRIPT}" >&2
  exit 1
fi

RID="${AIH_RUN_ID:-$(run_id)}"
export RID
timeout_ms="$(get_check_command_timeout_ms "$SCRIPT")"
log_file="$(check_log_path_for_script "$SCRIPT")"
label="npm run ${SCRIPT}"

echo "==> ${label} (timeout: $(( timeout_ms / 1000 ))s, log: ${log_file})"

if script_needs_test_stack "$SCRIPT"; then
  if ! prepare_test_stack_for_script "$SCRIPT"; then
    echo "ERROR: test stack reset failed before ${SCRIPT}" >&2
    exit 1
  fi
fi

npm_extra=("$@")
set +e
if [[ "$SCRIPT" == "build" ]]; then
  run_check_with_timeout_ms "$timeout_ms" --log "$log_file" --label "$label" --fn run_build_for_checks
elif ((${#npm_extra[@]} > 0)); then
  run_check_with_timeout_ms "$timeout_ms" --log "$log_file" --label "$label" npm run "$SCRIPT" "${npm_extra[@]}"
else
  run_check_with_timeout_ms "$timeout_ms" --log "$log_file" --label "$label" npm run "$SCRIPT"
fi
status=$?
set -e

echo "==> log file: ${log_file}"

if [[ "$status" -ne 0 && "$status" -ne "$AGENT_TIMEOUT_EXIT" ]]; then
  excerpt="$(extract_check_log_failure_excerpt "$log_file" 4000 2>/dev/null || true)"
  if [[ -n "$excerpt" ]]; then
    echo "==> failure excerpt:" >&2
    printf '%s\n' "$excerpt" >&2
  else
    emit_check_log_tail "$log_file" 30
  fi
fi

if [[ "$status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
  check_timeout_message "$timeout_ms" "$label"
  exit "$AGENT_TIMEOUT_EXIT"
fi
exit "$status"
