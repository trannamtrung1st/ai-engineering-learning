#!/usr/bin/env bash
# Build implementer/reviewer/tester prompt for a slice, or testgen prompt for a requirement tag
# Usage: build-prompt.sh <sliceId> [implementer|reviewer|tester]
#        build-prompt.sh testgen <requirementTag>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

MODE="${2:-implementer}"
SUBJECT_ID="${1:?id required}"

if [[ "$SUBJECT_ID" == "testgen" ]]; then
  MODE="testgen"
  SUBJECT_ID="${2:?requirement tag required for testgen}"
fi

if [[ "$MODE" != "implementer" && "$MODE" != "reviewer" && "$MODE" != "tester" && "$MODE" != "testgen" ]]; then
  echo "ERROR: mode must be implementer, reviewer, tester, or testgen" >&2
  exit 1
fi

if [[ "$MODE" == "testgen" ]]; then
  REQUIREMENT_TAG="$SUBJECT_ID"
  # shellcheck source=lib/doc-fingerprint.sh
  source "$(dirname "$0")/lib/doc-fingerprint.sh"
  # shellcheck source=lib/resolve-testgen-docs.sh
  source "$(dirname "$0")/lib/resolve-testgen-docs.sh"

  description="$REQUIREMENT_TAG — derive scenarios from docs below"
  acceptance="$REQUIREMENT_TAG"
  artifacts="$(test_case_artifact_path "$REQUIREMENT_TAG")"
  docs_list="$(resolve_docs_list_for_requirement_tag "$REQUIREMENT_TAG" | sed 's/^/- /')"
  doc_fp="$(compute_requirement_tag_doc_fingerprint "$REQUIREMENT_TAG")"
  artifact_path="$(test_case_artifact_path "$REQUIREMENT_TAG")"

  template_file="${HARNESS_ROOT}/agents/testgen.prompt.md"
  prompt="$(cat "$template_file")"
  prompt="${prompt//\{\{REQUIREMENT_TAG\}\}/$REQUIREMENT_TAG}"
  prompt="${prompt//\{\{PRODUCT_ITEM_ID\}\}/$REQUIREMENT_TAG}"
  prompt="${prompt//\{\{PRODUCT_ITEM_TITLE\}\}/$description}"
  prompt="${prompt//\{\{PRODUCT_ITEM_TRACEABILITY\}\}/$acceptance}"
  prompt="${prompt//\{\{SLICE_ID\}\}/$REQUIREMENT_TAG}"
  prompt="${prompt//\{\{SLICE_DESCRIPTION\}\}/$description}"
  prompt="${prompt//\{\{SLICE_ACCEPTANCE\}\}/$acceptance}"
  prompt="${prompt//\{\{SLICE_ARTIFACTS\}\}/$artifacts}"
  prompt="${prompt//\{\{SLICE_AGENT\}\}/testgen}"
  prompt="${prompt//\{\{SLICE_DOCS\}\}/$docs_list}"
  prompt="${prompt//\{\{DOC_FINGERPRINT\}\}/$doc_fp}"
  prompt="${prompt//\{\{TEST_CASE_ARTIFACT\}\}/$artifact_path}"
  coverage_hints="$(format_coverage_hints_block "$REQUIREMENT_TAG")"
  layer_policy="$(format_layer_policy_block "$REQUIREMENT_TAG")"
  existing_block="$(format_existing_artifact_review_block "$REQUIREMENT_TAG")"
  finish_hint="$(format_regeneration_finish_hint "$REQUIREMENT_TAG")"
  prompt="${prompt//\{\{COVERAGE_HINTS\}\}/$coverage_hints}"
  prompt="${prompt//\{\{LAYER_POLICY\}\}/$layer_policy}"
  prompt="${prompt//\{\{EXISTING_ARTIFACT_BLOCK\}\}/$existing_block}"
  prompt="${prompt//\{\{STALE_REGENERATION_BLOCK\}\}/$existing_block}"
  prompt="${prompt//\{\{REGENERATION_FINISH_HINT\}\}/$finish_hint}"
  printf '%s\n' "$prompt"
  exit 0
fi

SLICE_ID="$SUBJECT_ID"
slice_json="$(get_slice_json "$SLICE_ID")"
if [[ -z "$slice_json" || "$slice_json" == "null" ]]; then
  echo "ERROR: slice not found: $SLICE_ID" >&2
  exit 1
fi

description="$(echo "$slice_json" | jq -r '.description // ""')"
acceptance="$(echo "$slice_json" | jq -r '.acceptance | join(", ")')"
artifacts="$(echo "$slice_json" | jq -r '.completionArtifacts | join(", ")')"
agent_type="$(echo "$slice_json" | jq -r '.agent // "backend"')"
prompt_agent="$agent_type"
[[ "$MODE" == "tester" ]] && prompt_agent="tester"

docs_list="$(jq -r --arg id "$SLICE_ID" --arg agent "$prompt_agent" '
  (.slices[$id].docs // []) as $sliceDocs |
  (.agents[$agent].alwaysRead // []) as $always |
  ($always + $sliceDocs) | unique | .[] | "- " + .
' "$CONTEXT_MAP" 2>/dev/null || echo "$slice_json" | jq -r '.docs[]? | "- " + .')"

if [[ -z "$docs_list" ]]; then
  docs_list="$(echo "$slice_json" | jq -r '.docs[]? | "- " + .')"
fi

template_file="${HARNESS_ROOT}/agents/${MODE}.prompt.md"
if [[ ! -f "$template_file" ]]; then
  echo "ERROR: template not found: $template_file" >&2
  exit 1
fi

prompt="$(cat "$template_file")"
prompt="${prompt//\{\{SLICE_ID\}\}/$SLICE_ID}"
prompt="${prompt//\{\{SLICE_DESCRIPTION\}\}/$description}"
prompt="${prompt//\{\{SLICE_ACCEPTANCE\}\}/$acceptance}"
prompt="${prompt//\{\{SLICE_ARTIFACTS\}\}/$artifacts}"
prompt="${prompt//\{\{SLICE_AGENT\}\}/$agent_type}"
prompt="${prompt//\{\{SLICE_DOCS\}\}/$docs_list}"

missing_tags="$(slice_missing_test_case_tags "$SLICE_ID" | sed 's/^/- /')"
if [[ -n "$missing_tags" ]]; then
  prompt="${prompt}

## Missing test case artifacts

The following acceptance tags have no current TestGen artifacts yet — implement from slice docs and acceptance tags:

${missing_tags}
"
fi

if [[ "$MODE" == "implementer" ]]; then
  check_timeout_budgets="$(format_check_timeout_budgets_block 2>/dev/null || true)"
  prompt="${prompt//\{\{CHECK_TIMEOUT_BUDGETS\}\}/$check_timeout_budgets}"
  screenshot_block=""
  if slice_uses_browser_mcp "$SLICE_ID"; then
    screenshot_block="$(format_screenshot_dir_block "$SLICE_ID" implementer 2>/dev/null || true)"
  fi
  prompt="${prompt//\{\{SCREENSHOT_DIR_BLOCK\}\}/$screenshot_block}"

  prior_gate_feedback="$(build_implementer_prior_gate_feedback "$SLICE_ID" 2>/dev/null || true)"
  if [[ -n "$prior_gate_feedback" ]]; then
    prompt="${prompt}

${prior_gate_feedback}"
  fi
fi

if [[ "$MODE" == "tester" ]]; then
  screenshot_block="$(format_screenshot_dir_block "$SLICE_ID" browser-test 2>/dev/null || true)"
  prompt="${prompt//\{\{SCREENSHOT_DIR_BLOCK\}\}/$screenshot_block}"
  playwright_path="$(playwright_output_path_for_slice "$SLICE_ID")"
  ux_bugs_path="$(ux_bugs_path_for_slice_run "$SLICE_ID" "${AIH_RUN_ID:-$(run_id)}")"
  prompt="${prompt//\{\{PLAYWRIGHT_OUTPUT_PATH\}\}/$playwright_path}"
  prompt="${prompt//\{\{UX_BUGS_PATH\}\}/$ux_bugs_path}"
fi

printf '%s\n' "$prompt"
