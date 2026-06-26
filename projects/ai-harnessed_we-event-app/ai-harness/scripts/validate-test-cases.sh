#!/usr/bin/env bash
# Validate generated test case artifact for a product item
# Usage: validate-test-cases.sh <productItemId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

PRODUCT_ITEM_ID="${1:?product item id required}"
ARTIFACT="$(test_case_artifact_abs "$PRODUCT_ITEM_ID")"

VALID_TECHNIQUES="scenario-matrix flow-a flow-b flow-c module-integration http-contract rbac-negative pagination state-transition browser-journey concurrency boundary-error"

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

tag_matches_glob() {
  local tag="$1"
  local pattern="$2"
  [[ "$tag" =~ $pattern ]]
}

match_layer_policy_for_tag() {
  jq -c --arg tag "$PRODUCT_ITEM_ID" '
    . as $cfg |
    reduce (($cfg.validation.layerPolicy // {}) | to_entries[]) as $e (
      null;
      if ($tag | test("^" + ($e.key | gsub("\\*"; ".*")) + "$")) then $e.value else . end
    )
  ' "$TESTGEN_CONFIG" 2>/dev/null
}

match_technique_policy_for_tag() {
  jq -c --arg tag "$PRODUCT_ITEM_ID" '
    reduce ((.validation.techniquePolicy // {}) | to_entries[]) as $e (
      [];
      if ($tag | test("^" + ($e.key | gsub("\\*"; ".*")) + "$")) then . + $e.value else . end
    ) | unique
  ' "$TESTGEN_CONFIG" 2>/dev/null
}

resolved_docs_for_tag() {
  # shellcheck source=lib/resolve-testgen-docs.sh
  source "$(dirname "$0")/lib/resolve-testgen-docs.sh"
  resolve_docs_for_requirement_tag "$PRODUCT_ITEM_ID"
}

allowed_layers_json() {
  jq -c '.validation.allowedLayers // ["integration", "e2e", "browser"]' "$TESTGEN_CONFIG"
}

validate_structure() {
  local require_technique allowed_layers
  require_technique="$(jq -r '.validation.requireTechniqueField // true' "$TESTGEN_CONFIG")"
  allowed_layers="$(allowed_layers_json)"
  local errors
  errors="$(jq -r --arg req "$require_technique" --argjson allowed "$allowed_layers" '
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
      (if $req == "true" then req(.; "technique") else empty end),
      (req(.; "priority")),
      (req(.; "traceability")),
      (req(.; "title")),
      (req(.; "steps")),
      (req(.; "expected")),
      (if (.category | IN("functional","non-functional","edge")) | not then "invalid category: \(.id)" else empty end),
      (if (.layer | IN($allowed[])) | not then "invalid layer: \(.id) (allowed: \($allowed | join(", ")))" else empty end),
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

  local case_id technique
  while IFS=$'\t' read -r case_id technique; do
    [[ -z "$case_id" ]] && continue
    if ! echo "$VALID_TECHNIQUES" | grep -qw "$technique"; then
      FAILURES+=("invalid technique on ${case_id}: ${technique}")
      PASS=false
    fi
  done < <(jq -r '.cases[] | [.id, (.technique // "")] | @tsv' "$ARTIFACT")
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

validate_allowed_layers() {
  local allowed_layers
  allowed_layers="$(allowed_layers_json)"
  local invalid
  invalid="$(jq -r --argjson allowed "$allowed_layers" '
    .cases[] |
    select((.layer | IN($allowed[])) | not) |
    "forbidden layer \(.layer) on \(.id) (allowed: \($allowed | join(", ")))"
  ' "$ARTIFACT" 2>/dev/null || true)"

  if [[ -n "$invalid" ]]; then
    while IFS= read -r err; do
      [[ -z "$err" ]] && continue
      FAILURES+=("$err")
      PASS=false
    done <<< "$invalid"
  fi
}

validate_layer_policy() {
  local policy_json
  policy_json="$(match_layer_policy_for_tag)"
  [[ -z "$policy_json" || "$policy_json" == "null" ]] && return 0

  local layer min_count count
  while IFS=$'\t' read -r layer min_count; do
    [[ -z "$layer" ]] && continue
    count="$(jq -r --arg layer "$layer" '[.cases[] | select(.layer == $layer)] | length' "$ARTIFACT")"
    if [[ "$count" -lt "$min_count" ]]; then
      FAILURES+=("layerPolicy: ${layer} requires ${min_count}, found ${count}")
      PASS=false
    fi
  done < <(echo "$policy_json" | jq -r '.minPerLayer // {} | to_entries[] | [.key, (.value | tostring)] | @tsv')

  local required_layer
  while IFS= read -r required_layer; do
    [[ -z "$required_layer" ]] && continue
    count="$(jq -r --arg layer "$required_layer" '[.cases[] | select(.layer == $layer)] | length' "$ARTIFACT")"
    if [[ "$count" -lt 1 ]]; then
      FAILURES+=("layerPolicy: required layer ${required_layer} missing")
      PASS=false
    fi
  done < <(echo "$policy_json" | jq -r '.requiredLayers[]?')
}

validate_browser_required() {
  local pattern min_browser count
  min_browser="$(jq -r '.validation.browserRequiredWhen.minBrowserCases // 1' "$TESTGEN_CONFIG")"
  while IFS= read -r pattern; do
    [[ -z "$pattern" ]] && continue
    if tag_matches_glob "$PRODUCT_ITEM_ID" "$pattern"; then
      count="$(jq -r '[.cases[] | select(.layer == "browser")] | length' "$ARTIFACT")"
      if [[ "$count" -lt "$min_browser" ]]; then
        FAILURES+=("browserRequiredWhen: ${PRODUCT_ITEM_ID} requires ${min_browser} browser case(s), found ${count}")
        PASS=false
      fi
      return 0
    fi
  done < <(jq -r '.validation.browserRequiredWhen.tagMatches[]?' "$TESTGEN_CONFIG")
}

validate_technique_policy() {
  local require_technique
  require_technique="$(jq -r '.validation.requireTechniqueField // true' "$TESTGEN_CONFIG")"
  [[ "$require_technique" != "true" ]] && return 0

  local techniques technique count
  while IFS= read -r technique; do
    [[ -z "$technique" ]] && continue
    count="$(jq -r --arg t "$technique" '[.cases[] | select(.technique == $t)] | length' "$ARTIFACT")"
    if [[ "$count" -lt 1 ]]; then
      FAILURES+=("techniquePolicy: missing technique ${technique}")
      PASS=false
    fi
  done < <(match_technique_policy_for_tag | jq -r '.[]?')

  local docs_list
  docs_list="$(resolved_docs_for_tag | tr '\n' ' ')"

  local rule tag_pattern docs_include
  while IFS= read -r rule; do
    [[ -z "$rule" ]] && continue
    tag_pattern="$(echo "$rule" | jq -r '.tagMatches')"
    docs_include="$(echo "$rule" | jq -r '.docsInclude // empty')"
    if ! tag_matches_glob "$PRODUCT_ITEM_ID" "$tag_pattern"; then
      continue
    fi
    if [[ -n "$docs_include" && "$docs_list" != *"$docs_include"* ]]; then
      continue
    fi
    while IFS= read -r technique; do
      [[ -z "$technique" ]] && continue
      count="$(jq -r --arg t "$technique" '[.cases[] | select(.technique == $t)] | length' "$ARTIFACT")"
      if [[ "$count" -lt 1 ]]; then
        FAILURES+=("techniqueWhen: missing technique ${technique} (rule: ${tag_pattern})")
        PASS=false
      fi
    done < <(echo "$rule" | jq -r '.require[]?')
  done < <(jq -c '.validation.techniqueWhen[]?' "$TESTGEN_CONFIG")
}

validate_structure
validate_product_item_match
validate_min_per_category
validate_traceability_match
validate_allowed_layers
validate_layer_policy
validate_browser_required
validate_technique_policy

if [[ "$PASS" == true ]]; then
  echo "OK: test cases valid for ${PRODUCT_ITEM_ID} ($(jq '.cases | length' "$ARTIFACT") cases)"
  exit 0
fi

echo "ERROR: test case validation failed for ${PRODUCT_ITEM_ID}:" >&2
printf '  - %s\n' "${FAILURES[@]}" >&2
exit 1
