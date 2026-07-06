#!/usr/bin/env bash
# Wrapper: exit 1 if any backlog acceptance tag has current: false in test-case-index
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

stale="$(list_stale_requirement_tags)"
if [[ -n "$stale" ]]; then
  aih_err "Stale test case tags (run npm run aih:testgen:loop first):"
  printf '%s\n' "$stale"
  exit 1
fi

exec ./ai-harness/scripts/ralph-loop.sh "$@"
