#!/usr/bin/env bash
# Sync generated test cases into slice backlog metadata for slices referencing this product item
# Usage: sync-test-cases-to-backlog.sh <productItemId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

PRODUCT_ITEM_ID="${1:?product item id required}"
ARTIFACT="$(test_case_artifact_abs "$PRODUCT_ITEM_ID")"

if [[ ! -f "$ARTIFACT" ]]; then
  echo "ERROR: artifact not found: $ARTIFACT" >&2
  exit 1
fi

browser_scenarios="$(jq -r '[.cases[] | select(.layer == "browser") | .title] | unique | .[]' "$ARTIFACT")"

tmp="$(mktemp)"
jq --arg ref "$PRODUCT_ITEM_ID" \
  --argjson browser "$(jq -R -s 'split("\n") | map(select(length>0))' <<< "$browser_scenarios")" \
  '
  .slices |= map(
    if (.acceptance // [] | index($ref)) then
      (if ($browser | length) > 0 then
        .browserTestScenarios = ((.browserTestScenarios // []) + $browser | unique)
      else . end)
      | .testRequirements = (.testRequirements // {})
      | .testRequirements.acceptanceTags = (
          ((.testRequirements.acceptanceTags // []) + [$ref]) | unique
        )
    else . end
  )
' "$BACKLOG" > "$tmp" && mv "$tmp" "$BACKLOG"

echo "==> Synced test cases to slices referencing ${PRODUCT_ITEM_ID}"
