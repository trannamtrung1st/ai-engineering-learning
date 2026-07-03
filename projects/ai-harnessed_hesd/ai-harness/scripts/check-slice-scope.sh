#!/usr/bin/env bash
# Mechanical scope gate — changed files must match slice allowlist
# Usage: check-slice-scope.sh <sliceId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

SLICE_ID="${1:?slice id required}"
cd "$REPO_ROOT"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  aih_check_skip "slice scope gate (not a git repo)"
  exit 0
fi

violations="$(check_slice_scope_violations "$SLICE_ID" 2>/dev/null || true)"
if [[ -z "$violations" ]]; then
  aih_ok "slice scope gate: ${SLICE_ID} — all changed files in allowlist"
  exit 0
fi

aih_err "slice scope gate failed for ${SLICE_ID} — out-of-scope paths:"
printf '%s\n' "$violations"
exit 1
