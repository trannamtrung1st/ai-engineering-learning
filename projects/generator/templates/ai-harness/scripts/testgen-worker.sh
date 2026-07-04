#!/usr/bin/env bash
# TestGen worker — process an assigned list of requirement tags sequentially.
# Retries each tag until it passes validation before moving to the next.
# Usage: testgen-worker.sh <worker-id> <tags-file>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

WORKER_ID="${1:?worker id required}"
TAGS_FILE="${2:?tags file required}"

if [[ ! -f "$TAGS_FILE" ]]; then
  aih_err "Tags file not found: ${TAGS_FILE}"
  exit 1
fi

export AIH_TESTGEN_WORKER_ID="$WORKER_ID"

aih_section "TestGen worker ${WORKER_ID}" iteration

assigned=0
failed=0
tag=""
status=0

while IFS= read -r tag || [[ -n "$tag" ]]; do
  [[ -z "$tag" ]] && continue
  assigned=$((assigned + 1))

  if requirement_tag_test_cases_current "$tag"; then
    aih_info "Skipping ${tag} (already current)"
    continue
  fi

  aih_step "Worker ${WORKER_ID}: generating test cases for ${tag}"
  set +e
  run_testgen_tag_until_current "$tag" "$WORKER_ID"
  status=$?
  set -e

  if [[ "$status" -ne 0 ]] || ! requirement_tag_test_cases_current "$tag"; then
    failed=$((failed + 1))
    aih_warn "Worker ${WORKER_ID}: ${tag} did not pass (status=${status})"
  fi
done < "$TAGS_FILE"

if [[ "$assigned" -eq 0 ]]; then
  aih_info "Worker ${WORKER_ID}: no tags assigned"
  echo "TESTGEN_WORKER_COMPLETE worker=${WORKER_ID}"
  exit 0
fi

still_pending=0
while IFS= read -r tag || [[ -n "$tag" ]]; do
  [[ -z "$tag" ]] && continue
  if ! requirement_tag_test_cases_current "$tag"; then
    still_pending=$((still_pending + 1))
  fi
done < "$TAGS_FILE"

if [[ "$still_pending" -eq 0 ]]; then
  aih_ok "Worker ${WORKER_ID}: all assigned tags current"
  echo "TESTGEN_WORKER_COMPLETE worker=${WORKER_ID}"
  exit 0
fi

aih_warn "Worker ${WORKER_ID}: ${still_pending} assigned tag(s) still not current (${failed} failed this run)"
exit 1
