#!/usr/bin/env bash
# Check doc drift for slice plans; mark plan-index stale when slice inputs change
# Usage: check-plan-drift.sh [--quiet] [sliceId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/doc-fingerprint.sh
source "$(dirname "$0")/lib/doc-fingerprint.sh"

require_harness_deps
cd "$REPO_ROOT"

QUIET=false
TARGET_SLICE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet|-q)
      QUIET=true
      shift
      ;;
    *)
      TARGET_SLICE="$1"
      shift
      ;;
  esac
done

DRIFT_COUNT=0

check_slice_plan_drift() {
  local slice_id="$1"
  local stored_fp live_fp current
  [[ -n "$slice_id" ]] || return 0
  if ! slice_requires_plan "$slice_id"; then
    return 0
  fi

  ensure_plan_index
  stored_fp="$(jq -r --arg id "$slice_id" '.tags[$id].docFingerprint // ""' "$PLAN_INDEX")"
  live_fp="$(compute_slice_plan_fingerprint "$slice_id")"
  current="$(jq -r --arg id "$slice_id" '.tags[$id].current // false' "$PLAN_INDEX")"

  if [[ -z "$stored_fp" || "$stored_fp" == "null" ]]; then
    if [[ "$current" == "true" ]]; then
      echo "==> ${slice_id}: no stored plan fingerprint but marked current — resetting"
      invalidate_slice_plan "$slice_id" "missing stored fingerprint"
      DRIFT_COUNT=$((DRIFT_COUNT + 1))
    fi
    return 0
  fi

  if [[ "$stored_fp" != "$live_fp" ]]; then
    echo "==> ${slice_id}: plan drift detected"
    echo "    stored:  ${stored_fp}"
    echo "    current: ${live_fp}"
    invalidate_slice_plan "$slice_id" "doc or acceptance/testingPlanRefs changed"
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
    return 0
  fi

  local artifact
  artifact="$(slice_plan_artifact_abs "$slice_id")"
  if [[ "$current" == "true" && ! -f "$artifact" ]]; then
    echo "==> ${slice_id}: plan artifact missing — resetting plan state"
    invalidate_slice_plan "$slice_id" "plan artifact missing"
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
  fi
}

if [[ -n "$TARGET_SLICE" ]]; then
  check_slice_plan_drift "$TARGET_SLICE"
else
  local_id=""
  while IFS= read -r local_id; do
    [[ -z "$local_id" ]] && continue
    check_slice_plan_drift "$local_id"
  done < <(jq -r '.slices[]? | select(.passes == false) | .id' "$BACKLOG")
fi

if [[ "$DRIFT_COUNT" -gt 0 ]]; then
  echo "==> Plan drift: ${DRIFT_COUNT} slice(s) marked stale (Ralph will replan before implement)"
  exit 1
fi

if [[ "$QUIET" != true ]]; then
  echo "==> No plan drift detected"
fi
exit 0
