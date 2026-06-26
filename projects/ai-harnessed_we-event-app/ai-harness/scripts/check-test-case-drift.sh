#!/usr/bin/env bash
# Check doc drift for requirement tags; reset passes on referencing slices
# Usage: check-test-case-drift.sh [--quiet] [requirementTag]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/doc-fingerprint.sh
source "$(dirname "$0")/lib/doc-fingerprint.sh"

require_harness_deps
cd "$REPO_ROOT"

QUIET=false
TARGET_TAG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet|-q)
      QUIET=true
      shift
      ;;
    *)
      TARGET_TAG="$1"
      shift
      ;;
  esac
done

DRIFT_COUNT=0

check_tag_drift() {
  local requirement_tag="$1"
  local stored_fp live_fp
  stored_fp="$(jq -r --arg id "$requirement_tag" '.tags[$id].docFingerprint // ""' "$TEST_CASE_INDEX")"

  live_fp="$(compute_requirement_tag_doc_fingerprint "$requirement_tag")"

  if [[ -z "$stored_fp" || "$stored_fp" == "null" ]]; then
    if requirement_tag_test_cases_current "$requirement_tag"; then
      echo "==> ${requirement_tag}: no stored fingerprint but marked current — resetting"
      reset_requirement_tag_on_doc_drift "$requirement_tag" "$live_fp"
      DRIFT_COUNT=$((DRIFT_COUNT + 1))
    fi
    return 0
  fi

  if [[ "$stored_fp" != "$live_fp" ]]; then
    echo "==> ${requirement_tag}: doc drift detected"
    echo "    stored:  ${stored_fp}"
    echo "    current: ${live_fp}"
    reset_requirement_tag_on_doc_drift "$requirement_tag" "$live_fp"
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
    return 0
  fi

  local artifact
  artifact="$(test_case_artifact_abs "$requirement_tag")"
  if requirement_tag_test_cases_current "$requirement_tag" && [[ ! -f "$artifact" ]]; then
    echo "==> ${requirement_tag}: artifact missing — resetting test case state"
    reset_requirement_tag_on_doc_drift "$requirement_tag" "$live_fp"
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
  fi
}

if [[ -n "$TARGET_TAG" ]]; then
  check_tag_drift "$TARGET_TAG"
else
  local_id=""
  while IFS= read -r local_id; do
    [[ -z "$local_id" ]] && continue
    check_tag_drift "$local_id"
  done < <(all_requirement_tags_sorted)
fi

if [[ "$DRIFT_COUNT" -gt 0 ]]; then
  echo "==> Doc drift: ${DRIFT_COUNT} requirement tag(s) reset"
  exit 1
fi

if [[ "$QUIET" != true ]]; then
  echo "==> No doc drift detected"
fi
exit 0
