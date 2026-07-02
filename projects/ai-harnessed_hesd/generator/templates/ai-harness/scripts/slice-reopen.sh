#!/usr/bin/env bash
# Reopen a backlog slice with history (does not set loop override)
# Usage: slice-reopen.sh <slice-id> --reason "why reopening"
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

SLICE_ID=""
REASON=""

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
  aih_err "Usage: slice-reopen.sh <slice-id> --reason \"why reopening\""
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

mark_slice_reopened "$SLICE_ID" "$REASON" "human" "manual"
aih_ok "Reopened slice ${SLICE_ID} (passes: false). History recorded."
