#!/usr/bin/env bash
# Validate work plan markdown
# Usage: validate-work-plan.sh <sliceId> [--quiet] [--plan-file <path>]
# Without --plan-file, reads legacy path ai-harness/plans/<slice-id>.md (manual use only).
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

SLICE_ID="${1:?slice id required}"
shift
QUIET=false
PLAN_FILE_OVERRIDE=""

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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet)
      QUIET=true
      shift
      ;;
    --plan-file)
      PLAN_FILE_OVERRIDE="${2:?--plan-file requires a path}"
      shift 2
      ;;
    *)
      log_err "unknown argument: $1"
      exit 1
      ;;
  esac
done

if ! slice_requires_plan "$SLICE_ID"; then
  log_ok "work plan validation skipped (requiresPlan=false): ${SLICE_ID}"
  exit 0
fi

if [[ -n "$PLAN_FILE_OVERRIDE" ]]; then
  if [[ "$PLAN_FILE_OVERRIDE" = /* ]]; then
    plan_path="$PLAN_FILE_OVERRIDE"
  else
    plan_path="${REPO_ROOT}/${PLAN_FILE_OVERRIDE}"
  fi
else
  plan_path="$(work_plan_artifact_abs "$SLICE_ID")"
fi
if [[ ! -f "$plan_path" ]]; then
  if [[ -n "$PLAN_FILE_OVERRIDE" ]]; then
    log_err "plan file missing: ${PLAN_FILE_OVERRIDE}"
  else
    log_err "plan artifact missing: $(work_plan_artifact_path "$SLICE_ID") (use --plan-file for ephemeral plans)"
  fi
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

if slice_has_prior_gate_failures "$SLICE_ID"; then
  required_headings=(
    "Prior gate failure remediation"
    "${required_headings[@]}"
  )
fi

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
deferrals_section="$(extract_section "Risks and deferrals")"
remediation_section=""
if slice_has_prior_gate_failures "$SLICE_ID"; then
  remediation_section="$(extract_section "Prior gate failure remediation")"
  if [[ -z "${remediation_section//[[:space:]]/}" ]]; then
    FAILURES+=("Prior gate failure remediation section must list concrete fix steps for each prior gate failure")
  elif ! grep -qE '^[[:space:]]*([-*]|[0-9]+[.)])' <<< "$remediation_section"; then
    FAILURES+=("Prior gate failure remediation section must use bullets or numbered fix steps")
  fi
  impl_section="$(extract_section "Implementation sequence")"
  if [[ -z "${impl_section//[[:space:]]/}" ]] || ! grep -qE '^[[:space:]]*1[.)]' <<< "$impl_section"; then
    FAILURES+=("Implementation sequence must start with step 1 listing remediation fixes when prior gate failures exist")
  fi
fi

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

# completionArtifacts may use globs (e.g. dir/*.integration.test.ts); accept concrete
# filenames in the same directory that match the glob suffix.
completion_artifact_in_section() {
  local artifact="$1"
  local section="$2"
  local base="${artifact##*/}"

  if grep -qF "$artifact" <<< "$section" || grep -qF "$base" <<< "$section"; then
    return 0
  fi

  if [[ "$base" == *'*'* ]]; then
    local dir_prefix="${artifact%/*}/"
    local suffix="${base#\*}"
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      if [[ "$line" == *"${dir_prefix}"* && "$line" == *"${suffix}"* ]]; then
        local after_dir="${line#*${dir_prefix}}"
        if [[ -n "$after_dir" && "$after_dir" != "$suffix" && "$after_dir" == *"${suffix}"* ]]; then
          return 0
        fi
      fi
    done <<< "$section"
  fi

  if [[ "$artifact" == */ ]]; then
    local dir_no_slash="${artifact%/}"
    if grep -qF "$dir_no_slash" <<< "$section"; then
      return 0
    fi
  fi

  return 1
}

while IFS= read -r artifact; do
  [[ -z "$artifact" ]] && continue
  if [[ -n "$files_section" ]]; then
    if ! completion_artifact_in_section "$artifact" "$files_section"; then
      FAILURES+=("completionArtifacts path not mentioned in Files to create or modify: ${artifact}")
    fi
  elif ! completion_artifact_in_section "$artifact" "$(cat "$plan_path")"; then
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
    # A case is "accounted for" if it is either implemented (referenced in the
    # Test strategy section) or explicitly deferred (listed under Risks and
    # deferrals). Cross-cutting acceptance tags (e.g. NFR-05/NFR-08) legitimately
    # spread their cases across multiple slices, so a single slice plan may cover
    # only a subset and defer the rest to downstream slices.
    if grep -qF "$case_id" <<< "$test_strategy_section"; then
      continue
    fi
    if grep -qF "$case_id" <<< "$deferrals_section"; then
      continue
    fi
    FAILURES+=("TestGen case ${case_id} (${tag}) not referenced in Test strategy or deferred in Risks and deferrals")
  done < <(jq -r '.cases[]? | select((.layer // "") | test("^(integration|e2e|browser)$")) | .id // empty' "$artifact_abs" 2>/dev/null)
done < <(echo "$slice_json" | jq -r '.acceptance[]? // empty')

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  log_err "work plan validation failed for ${SLICE_ID}:"
  printf '%s\n' "${FAILURES[@]}" >&2
  exit 1
fi

log_ok "work plan validation passed: ${SLICE_ID}"
exit 0
