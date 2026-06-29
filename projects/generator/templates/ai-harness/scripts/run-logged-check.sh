#!/usr/bin/env bash
# Run one root package.json script with harness timeout, live output, heartbeat, and log file.
# Use for ad-hoc agent self-checks (especially test:integration) to avoid silent hangs.
#
# Usage: run-logged-check.sh <npm-script>
# Example: ./ai-harness/scripts/run-logged-check.sh test:integration
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

SCRIPT="${1:?npm script name required — e.g. test:integration}"
shift || true

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

set +e
if [[ "$SCRIPT" == "build" ]]; then
  run_check_with_timeout_ms "$timeout_ms" --log "$log_file" --label "$label" --fn run_build_for_checks
else
  run_check_with_timeout_ms "$timeout_ms" --log "$log_file" --label "$label" npm run "$SCRIPT" "$@"
fi
status=$?
set -e

echo "==> log file: ${log_file}"

if [[ "$status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
  check_timeout_message "$timeout_ms" "$label"
  exit "$AGENT_TIMEOUT_EXIT"
fi
exit "$status"
