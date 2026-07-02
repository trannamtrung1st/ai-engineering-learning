#!/usr/bin/env bash
# Validate whole-app-backlog.json structure before Ralph iterations
# Usage: validate-backlog.sh [--quiet]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

QUIET=false
if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=true
fi

log_err() {
  if [[ "$QUIET" == true ]]; then
    echo "$1" >&2
  else
    aih_err "$1"
  fi
}

log_ok() {
  if [[ "$QUIET" != true ]]; then
    aih_ok "$1"
  fi
}

if [[ ! -f "$BACKLOG" ]]; then
  log_err "backlog not found: $BACKLOG"
  exit 1
fi

if ! jq empty "$BACKLOG" 2>/dev/null; then
  log_err "invalid JSON in $BACKLOG"
  exit 1
fi

PASS=true
FAILURES=()

while IFS=$'\t' read -r slice_id issue; do
  [[ -z "$slice_id" ]] && continue
  FAILURES+=("[$slice_id] $issue")
  PASS=false
done < <(jq -r '
  .slices[]? |
  .id as $id |
  (
    if ($id | length) == 0 then
      ["", "missing slice id"]
    elif (.completionArtifacts | type) != "array" then
      [$id, "completionArtifacts must be a non-null array (check for typos such as leading spaces in the key name)"]
    elif (.acceptance | type) != "array" then
      [$id, "acceptance must be a non-null array"]
    else
      empty
    end
  ),
  (
    to_entries[]
    | select(.key | test("^\\s+|\\s+$"))
    | [$id, "suspicious key \"\(.key)\" — did you mean \"\(.key | gsub("^\\s+|\\s+$"; ""))\"?"]
  ),
  (
    (.history // [])[]
    | if (.at | type) != "string" or (.at | length) == 0 then
        [$id, "history entry missing string at"]
      elif (.kind | type) != "string" or (.kind | length) == 0 then
        [$id, "history entry missing string kind"]
      elif (.reason | type) != "string" or (.reason | length) == 0 then
        [$id, "history entry missing string reason"]
      elif (.source | type) != "string" or (.source | length) == 0 then
        [$id, "history entry missing string source"]
      else empty end
  )
' "$BACKLOG" 2>/dev/null)

if [[ "$PASS" != true ]]; then
  log_err "whole-app-backlog.json validation failed:"
  printf '%s\n' "${FAILURES[@]}" >&2
  exit 1
fi

log_ok "whole-app-backlog.json validation passed"
exit 0
