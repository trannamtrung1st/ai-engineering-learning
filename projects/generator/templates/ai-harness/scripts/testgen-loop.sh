#!/usr/bin/env bash
# TestGen loop — generate test cases from docs for all slices
# Usage: testgen-loop.sh [maxIterations]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

max="${1:-$(jq -r '.loop.maxIterations // 30' "$TESTGEN_CONFIG")}"
iter=0

aih_section "TestGen loop (max=${max})" loop
print_harness_env

while [[ "$iter" -lt "$max" ]]; do
  if all_test_cases_current; then
    echo "TESTGEN_COMPLETE"
    exit 0
  fi

  iter=$((iter + 1))
  aih_section "TestGen iteration ${iter}/${max}" iteration

  set +e
  ./ai-harness/scripts/testgen-once.sh
  status=$?
  set -e

  if [[ "$status" -ne 0 ]]; then
    aih_warn "TestGen iteration ${iter} did not pass; continuing with fresh context"
  fi

  if all_test_cases_current; then
    echo "TESTGEN_COMPLETE"
    exit 0
  fi
done

aih_err "Max TestGen iterations (${max}) reached"
remaining=0
pending=0
tag=""
while IFS= read -r tag; do
  [[ -z "$tag" ]] && continue
  remaining=$((remaining + 1))
  if ! requirement_tag_test_cases_current "$tag"; then
    pending=$((pending + 1))
  fi
done < <(all_requirement_tags_sorted)
aih_info "Remaining requirement tags without test cases: ${pending} / ${remaining}"
exit 1
