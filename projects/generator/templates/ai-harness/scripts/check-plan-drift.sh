#!/usr/bin/env bash
# Deprecated: Ralph replans from state every iteration (no plan-index).
# Usage: check-plan-drift.sh [--quiet] [sliceId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

QUIET=false
if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=true
  shift
fi

if [[ "$QUIET" != true ]]; then
  aih_info "Plan drift check skipped — work planner runs every Ralph iteration from current state (no plan-index)."
fi
exit 0
