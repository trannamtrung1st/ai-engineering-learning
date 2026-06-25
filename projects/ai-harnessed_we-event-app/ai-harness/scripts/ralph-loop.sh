#!/usr/bin/env bash
# Ralph loop — fresh Cursor CLI context each iteration
# Usage: ralph-loop.sh [maxIterations]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

cd "$REPO_ROOT"

max="${1:-$(jq -r '.loop.maxIterations // 30' "$LOOP_CONFIG")}"
iter=0

echo "==> Ralph loop starting (max=${max})"
print_harness_env

while [[ "$iter" -lt "$max" ]]; do
  if all_slices_pass; then
    echo "COMPLETE"
    exit 0
  fi

  iter=$((iter + 1))
  echo ""
  echo "========== Iteration ${iter}/${max} =========="

  set +e
  ./ai-harness/scripts/ralph-once.sh
  status=$?
  set -e

  if [[ "$status" -ne 0 ]]; then
    echo "==> Iteration ${iter} did not pass; continuing with fresh context"
  fi

  if all_slices_pass; then
    echo "COMPLETE"
    exit 0
  fi
done

echo "==> Max iterations (${max}) reached"
remaining="$(jq '[.slices[] | select(.passes == false)] | length' "$BACKLOG")"
echo "Remaining slices: ${remaining}"
exit 1
