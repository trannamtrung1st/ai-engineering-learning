#!/usr/bin/env bash
# Check doc drift for manual items; mark index stale
# Usage: check-manuals-drift.sh [--quiet] [manualItemId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/doc-fingerprint.sh
source "$(dirname "$0")/lib/doc-fingerprint.sh"

require_harness_deps
cd "$REPO_ROOT"

QUIET=false
TARGET_ITEM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet|-q)
      QUIET=true
      shift
      ;;
    *)
      TARGET_ITEM="$1"
      shift
      ;;
  esac
done

DRIFT_COUNT=0

check_item_drift() {
  local item_id="$1"
  local stored_fp live_fp artifact
  stored_fp="$(jq -r --arg id "$item_id" '.tags[$id].docFingerprint // ""' "$MANUALS_INDEX")"
  live_fp="$(compute_manual_item_doc_fingerprint "$item_id")"

  if [[ -z "$stored_fp" || "$stored_fp" == "null" ]]; then
    if manual_item_current "$item_id"; then
      echo "==> ${item_id}: no stored fingerprint but marked current — resetting"
      reset_manual_item_on_doc_drift "$item_id" "$live_fp"
      DRIFT_COUNT=$((DRIFT_COUNT + 1))
    fi
    return 0
  fi

  if [[ "$stored_fp" != "$live_fp" ]]; then
    echo "==> ${item_id}: doc drift detected"
    echo "    stored:  ${stored_fp}"
    echo "    current: ${live_fp}"
    reset_manual_item_on_doc_drift "$item_id" "$live_fp"
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
    return 0
  fi

  artifact="$(manual_artifact_abs "$item_id")"
  if manual_item_current "$item_id" && [[ ! -f "$artifact" ]]; then
    echo "==> ${item_id}: artifact missing — resetting manual state"
    reset_manual_item_on_doc_drift "$item_id" "$live_fp"
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
  fi
}

if [[ -n "$TARGET_ITEM" ]]; then
  check_item_drift "$TARGET_ITEM"
else
  local_id=""
  while IFS= read -r local_id; do
    [[ -z "$local_id" ]] && continue
    check_item_drift "$local_id"
  done < <(all_manual_item_ids_sorted)
fi

if [[ "$DRIFT_COUNT" -gt 0 ]]; then
  echo "==> Doc drift: ${DRIFT_COUNT} manual item(s) marked stale (run: npm run aih:manualsgen:loop)"
  exit 1
fi

if [[ "$QUIET" != true ]]; then
  echo "==> No manual doc drift detected"
fi
exit 0
