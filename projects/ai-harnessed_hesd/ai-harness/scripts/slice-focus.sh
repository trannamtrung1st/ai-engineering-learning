#!/usr/bin/env bash
# Set one-shot next-iteration slice override
# Usage: slice-focus.sh <slice-id> --reason "fix this next" [--reopen]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

SLICE_ID=""
REASON=""
REOPEN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason)
      REASON="${2:-}"
      shift 2
      ;;
    --reason=*)
      REASON="${1#--reason=}"
      shift
      ;;
    --reopen)
      REOPEN=true
      shift
      ;;
    -*)
      aih_err "Unknown option: $1"
      exit 1
      ;;
    *)
      if [[ -z "$SLICE_ID" ]]; then
        SLICE_ID="$1"
      else
        aih_err "Unexpected argument: $1"
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$SLICE_ID" ]]; then
  aih_err "Usage: slice-focus.sh <slice-id> --reason \"fix this next\" [--reopen]"
  exit 1
fi

if [[ -z "$REASON" ]]; then
  aih_err "--reason is required"
  exit 1
fi

slice_json="$(get_slice_json "$SLICE_ID")"
if [[ -z "$slice_json" || "$slice_json" == "null" ]]; then
  aih_err "Slice not found: ${SLICE_ID}"
  exit 1
fi

passes="$(echo "$slice_json" | jq -r '.passes // false')"
if [[ "$passes" == "true" && "$REOPEN" != true ]]; then
  aih_warn "Slice ${SLICE_ID} has passes: true — override is ignored until reopened. Use --reopen or npm run aih:slice:reopen."
fi

if [[ "$REOPEN" == true ]]; then
  mark_slice_reopened "$SLICE_ID" "$REASON" "human" "manual"
fi

set_loop_slice_override "$SLICE_ID" "$REASON" "slice-focus"
aih_ok "Next Ralph iteration will focus ${SLICE_ID} (one-shot override)."
