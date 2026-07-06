#!/usr/bin/env bash
# Validate slice implementation plan markdown before implementer runs
# Usage: validate-slice-plan.sh <sliceId> [--quiet]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

SLICE_ID="${1:?slice id required}"
QUIET=false
if [[ "${2:-}" == "--quiet" ]]; then
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

if ! slice_requires_plan "$SLICE_ID"; then
  log_ok "slice plan validation skipped (requiresPlan=false): ${SLICE_ID}"
  exit 0
fi

plan_path="$(slice_plan_artifact_abs "$SLICE_ID")"
if [[ ! -f "$plan_path" ]]; then
  log_err "plan artifact missing: $(slice_plan_artifact_path "$SLICE_ID")"
  exit 1
fi

slice_json="$(get_slice_json "$SLICE_ID")"
FAILURES=()

required_headings=(
  "Acceptance coverage"
  "Testing plan alignment"
  "Files to create or modify"
  "Test strategy"
  "Implementation sequence"
  "Risks and deferrals"
)

for heading in "${required_headings[@]}"; do
  if ! grep -qiE "^##[[:space:]]+${heading}[[:space:]]*$" "$plan_path"; then
    FAILURES+=("missing required heading: ## ${heading}")
  fi
done

extract_section() {
  local section_title="$1"
  awk -v title="$section_title" '
    BEGIN { in_section=0 }
    /^##[[:space:]]+/ {
      if (in_section) { exit }
      if (tolower($0) ~ ("^##[[:space:]]+" tolower(title) "[[:space:]]*$")) { in_section=1; next }
    }
    in_section { print }
  ' "$plan_path"
}

acceptance_section="$(extract_section "Acceptance coverage")"
testing_section="$(extract_section "Testing plan alignment")"
files_section="$(extract_section "Files to create or modify")"
test_strategy_section="$(extract_section "Test strategy")"

while IFS= read -r tag; do
  [[ -z "$tag" ]] && continue
  if ! grep -q "$tag" "$plan_path"; then
    FAILURES+=("acceptance tag not found in plan: ${tag}")
  fi
  if [[ -n "$acceptance_section" ]] && ! grep -q "$tag" <<< "$acceptance_section"; then
    FAILURES+=("acceptance tag missing from Acceptance coverage section: ${tag}")
  fi
done < <(echo "$slice_json" | jq -r '.acceptance[]? // empty')

while IFS= read -r ref; do
  [[ -z "$ref" ]] && continue
  if ! grep -qF "$ref" "$plan_path"; then
    FAILURES+=("testingPlanRefs entry not found in plan: ${ref}")
  fi
  if [[ -n "$testing_section" ]] && ! grep -qF "$ref" <<< "$testing_section"; then
    FAILURES+=("testingPlanRefs entry missing from Testing plan alignment section: ${ref}")
  fi
done < <(echo "$slice_json" | jq -r '.testingPlanRefs[]? // empty')

while IFS= read -r artifact; do
  [[ -z "$artifact" ]] && continue
  base="${artifact##*/}"
  if [[ -n "$files_section" ]]; then
    if ! grep -qF "$artifact" <<< "$files_section" && ! grep -qF "$base" <<< "$files_section"; then
      FAILURES+=("completionArtifacts path not mentioned in Files to create or modify: ${artifact}")
    fi
  elif ! grep -qF "$artifact" "$plan_path" && ! grep -qF "$base" "$plan_path"; then
    FAILURES+=("completionArtifacts path not mentioned in plan: ${artifact}")
  fi
done < <(echo "$slice_json" | jq -r '.completionArtifacts[]? // empty')

agent_type="$(echo "$slice_json" | jq -r '.agent // "backend"')"
case "$agent_type" in
  backend)
    if [[ -z "${test_strategy_section//[[:space:]]/}" ]] || ! grep -Eiq 'integration' <<< "$test_strategy_section"; then
      FAILURES+=("backend slice Test strategy section must mention integration layer")
    fi
    ;;
  frontend)
    if [[ -z "${test_strategy_section//[[:space:]]/}" ]]; then
      FAILURES+=("frontend slice Test strategy section must not be empty")
    else
      if ! grep -Eiq 'component' <<< "$test_strategy_section"; then
        FAILURES+=("frontend slice Test strategy must mention component layer")
      fi
      if ! grep -Eiq 'browser' <<< "$test_strategy_section"; then
        FAILURES+=("frontend slice Test strategy must mention browser layer")
      fi
    fi
    ;;
  test)
    if [[ -z "${test_strategy_section//[[:space:]]/}" ]] || ! grep -Eiq 'e2e|browser|integration' <<< "$test_strategy_section"; then
      FAILURES+=("test slice Test strategy section must mention e2e, browser, or integration layer")
    fi
    ;;
esac

while IFS= read -r tag; do
  [[ -z "$tag" ]] && continue
  artifact_rel="docs/test-cases/items/${tag}.json"
  artifact_abs="${REPO_ROOT}/${artifact_rel}"
  [[ -f "$artifact_abs" ]] || continue
  if ! requirement_tag_test_cases_current "$tag"; then
    continue
  fi
  while IFS= read -r case_id; do
    [[ -z "$case_id" ]] && continue
    if ! grep -qF "$case_id" <<< "$test_strategy_section" && ! grep -qF "$case_id" "$plan_path"; then
      FAILURES+=("TestGen case ${case_id} (${tag}) not referenced in Test strategy")
    fi
  done < <(jq -r '.cases[]? | select((.layer // "") | test("^(integration|e2e|browser)$")) | .id // empty' "$artifact_abs" 2>/dev/null)
done < <(echo "$slice_json" | jq -r '.acceptance[]? // empty')

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  log_err "slice plan validation failed for ${SLICE_ID}:"
  printf '%s\n' "${FAILURES[@]}" >&2
  exit 1
fi

log_ok "slice plan validation passed: ${SLICE_ID}"
exit 0
