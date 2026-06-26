#!/usr/bin/env bash
# Validate generated test case artifact for a product item
# Usage: validate-test-cases.sh <productItemId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

PRODUCT_ITEM_ID="${1:?product item id required}"
ARTIFACT="$(test_case_artifact_abs "$PRODUCT_ITEM_ID")"

if [[ ! -f "$ARTIFACT" ]]; then
  echo "ERROR: test case artifact not found: $ARTIFACT" >&2
  exit 1
fi

if ! jq empty "$ARTIFACT" 2>/dev/null; then
  echo "ERROR: invalid JSON in $ARTIFACT" >&2
  exit 1
fi

PASS=true
FAILURES=()

validate_structure() {
  local errors
  errors="$(jq -r '
    def req($o; $k): if ($o[$k] // null) == null then "\($k) missing" else empty end;
    . as $root |
    (req($root; "productItemId")),
    (req($root; "version")),
    (req($root; "docFingerprint")),
    (req($root; "generatedAt")),
    (req($root; "cases")),
    (if ($root.cases | type) != "array" then "cases must be array" else empty end),
    (if ($root.cases | length) < 1 then "cases must not be empty" else empty end),
    ($root.cases[] |
      (req(.; "id")),
      (req(.; "category")),
      (req(.; "layer")),
      (req(.; "priority")),
      (req(.; "traceability")),
      (req(.; "title")),
      (req(.; "steps")),
      (req(.; "expected")),
      (if (.category | IN("functional","non-functional","edge")) | not then "invalid category: \(.id)" else empty end),
      (if (.layer | IN("unit","integration","e2e","browser")) | not then "invalid layer: \(.id)" else empty end),
      (if (.traceability | length) < 1 then "traceability empty: \(.id)" else empty end)
    )
  ' "$ARTIFACT" 2>/dev/null || true)"

  if [[ -n "$errors" ]]; then
    while IFS= read -r err; do
      [[ -z "$err" ]] && continue
      FAILURES+=("$err")
      PASS=false
    done <<< "$errors"
  fi
}

validate_product_item_match() {
  local artifact_item
  artifact_item="$(jq -r '.productItemId' "$ARTIFACT")"
  if [[ "$artifact_item" != "$PRODUCT_ITEM_ID" ]]; then
    FAILURES+=("productItemId mismatch: expected ${PRODUCT_ITEM_ID}, got ${artifact_item}")
    PASS=false
  fi
}

validate_min_per_category() {
  local cat min_count count
  for cat in functional non-functional edge; do
    min_count="$(jq -r --arg c "$cat" '.validation.minCasesPerCategory[$c] // 0' "$TESTGEN_CONFIG")"
    count="$(jq -r --arg c "$cat" '[.cases[] | select(.category == $c)] | length' "$ARTIFACT")"
    if [[ "$count" -lt "$min_count" ]]; then
      FAILURES+=("minCasesPerCategory: ${cat} requires ${min_count}, found ${count}")
      PASS=false
    fi
  done
}

validate_traceability_match() {
  local require_match
  require_match="$(jq -r '.validation.requireTraceabilityMatch // true' "$TESTGEN_CONFIG")"
  [[ "$require_match" != "true" ]] && return 0

  local invalid
  invalid="$(jq -r --arg item "$PRODUCT_ITEM_ID" '
    if ([.cases[].traceability[]] | index($item) | not) then
      "product item \($item) not referenced in any case traceability"
    else empty end
  ' "$ARTIFACT" 2>/dev/null || true)"

  if [[ -n "$invalid" ]]; then
    FAILURES+=("$invalid")
    PASS=false
  fi
}

validate_structure
validate_product_item_match
validate_min_per_category
validate_traceability_match

if [[ "$PASS" == true ]]; then
  echo "OK: test cases valid for ${PRODUCT_ITEM_ID} ($(jq '.cases | length' "$ARTIFACT") cases)"
  exit 0
fi

echo "ERROR: test case validation failed for ${PRODUCT_ITEM_ID}:" >&2
printf '  - %s\n' "${FAILURES[@]}" >&2
exit 1
