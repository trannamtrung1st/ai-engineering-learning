#!/usr/bin/env bash
# Wrapper: exit 1 if any backlog acceptance tag has current: false in test-case-index
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

stale="$(jq -r '.tags | to_entries[] | select(.value.current == false) | .key' "$TEST_CASE_INDEX" 2>/dev/null || true)"
if [[ -n "$stale" ]]; then
  aih_err "Stale test case tags (run npm run aih:testgen:loop first):"
  printf '%s\n' "$stale"
  exit 1
fi

exec ./ai-harness/scripts/ralph-loop.sh "$@"
