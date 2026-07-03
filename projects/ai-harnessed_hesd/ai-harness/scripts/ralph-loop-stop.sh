#!/usr/bin/env bash
# Stop background Ralph loop if running
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

pidfile="${RUNS_DIR}/loop.pid"

if [[ ! -f "$pidfile" ]]; then
  echo "No loop pid file (${pidfile})"
  exit 0
fi

pid="$(cat "$pidfile")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  echo "Stopped loop (pid ${pid})"
else
  echo "Loop not running (stale pid ${pid})"
fi
rm -f "$pidfile"
