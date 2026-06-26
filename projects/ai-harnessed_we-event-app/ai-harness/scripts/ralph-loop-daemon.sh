#!/usr/bin/env bash
# Run Ralph loop in background (unattended). Logs to ai-harness/generated/runs/loop.log
# Usage: ralph-loop-daemon.sh [maxIterations]
# Env (optional, pass in shell): AIH_MODEL=auto npm run aih:loop:bg
# Stop: npm run aih:loop:stop
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
ensure_runs_dir

max="${1:-$(jq -r '.loop.maxIterations // 30' "$LOOP_CONFIG")}"
pidfile="${RUNS_DIR}/loop.pid"
logfile="${RUNS_DIR}/loop.log"

if [[ -f "$pidfile" ]]; then
  old_pid="$(cat "$pidfile")"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "Loop already running (pid ${old_pid}). Log: ${logfile}" >&2
    echo "Stop with: npm run aih:loop:stop" >&2
    exit 1
  fi
  rm -f "$pidfile"
fi

cd "$REPO_ROOT"

{
  echo "==> $(date -u +"%Y-%m-%dT%H:%M:%SZ") Ralph loop daemon starting (max=${max})"
  print_harness_env
} >>"$logfile"

nohup env AIH_MODEL="${AIH_MODEL:-}" AIH_REVIEWER_MODEL="${AIH_REVIEWER_MODEL:-}" \
  AIH_TESTER_MODEL="${AIH_TESTER_MODEL:-}" \
  AIH_SKIP_AGENT="${AIH_SKIP_AGENT:-}" AIH_SKIP_REVIEW="${AIH_SKIP_REVIEW:-}" \
  AIH_SKIP_BROWSER_TEST="${AIH_SKIP_BROWSER_TEST:-}" \
  ./ai-harness/scripts/ralph-loop.sh "$max" >>"$logfile" 2>&1 &
echo $! >"$pidfile"

echo "Ralph loop started in background (pid $(cat "$pidfile"), max=${max})"
print_harness_env
echo "Log: ${logfile}"
echo "Tail: tail -f ${logfile}"
echo "Stop: npm run aih:loop:stop"
