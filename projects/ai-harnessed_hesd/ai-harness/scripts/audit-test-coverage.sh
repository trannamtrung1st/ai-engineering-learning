#!/usr/bin/env bash
# Audit test case coverage techniques and layers (report-only, no fail)
# Usage: audit-test-coverage.sh [productItemId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/resolve-testgen-docs.sh
source "$(dirname "$0")/lib/resolve-testgen-docs.sh"

require_harness_deps

audit_tag() {
  local tag="$1"
  local artifact
  artifact="$(test_case_artifact_abs "$tag")"

  if [[ ! -f "$artifact" ]]; then
    echo "${tag}: MISSING artifact"
    return 0
  fi

  echo "==> ${tag} ($(jq '.cases | length' "$artifact") cases)"

  local layers techniques
  layers="$(jq -r '[.cases[].layer] | group_by(.) | map("\(.[0]):\(length)") | join(", ")' "$artifact")"
  techniques="$(jq -r '[.cases[].technique // "none"] | group_by(.) | map("\(.[0]):\(length)") | join(", ")' "$artifact")"
  echo "    layers: ${layers:-none}"
  echo "    techniques: ${techniques:-none}"

  local validate_out validate_status
  set +e
  validate_out="$(./ai-harness/scripts/validate-test-cases.sh "$tag" 2>&1)"
  validate_status=$?
  set -e

  if [[ "$validate_status" -eq 0 ]]; then
    echo "    validation: PASS"
  else
    echo "    validation: FAIL"
    while IFS= read -r line; do
      [[ "$line" == ERROR:* ]] && continue
      [[ "$line" == "  - "* ]] && echo "      ${line#  - }"
    done <<< "$validate_out"
  fi

  local hints
  hints="$(resolve_coverage_hints_for_requirement_tag "$tag")"
  if [[ -n "$hints" ]]; then
    echo "    doc hints:"
    while IFS= read -r hint; do
      [[ -z "$hint" ]] && continue
      echo "      - ${hint}"
    done <<< "$hints"
  fi
  echo ""
}

if [[ $# -ge 1 ]]; then
  audit_tag "$1"
  exit 0
fi

echo "Test case coverage audit"
echo ""

tag=""
while IFS= read -r tag; do
  [[ -z "$tag" ]] && continue
  audit_tag "$tag"
done < <(all_requirement_tags_sorted)
