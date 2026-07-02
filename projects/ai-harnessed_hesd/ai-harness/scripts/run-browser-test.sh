#!/usr/bin/env bash
# Browser functional/UI test via Playwright MCP
# Usage: run-browser-test.sh <sliceId> [runId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
require_agent

SLICE_ID="${1:-$(pick_next_slice_id)}"
RUN_ID="${2:-${AIH_RUN_ID:-}}"
if [[ -z "$SLICE_ID" ]]; then
  echo "ERROR: no slice to test" >&2
  exit 1
fi
RID="${RUN_ID:-$(run_id)}"
ensure_runs_dir

cd "$REPO_ROOT"

browser_test_required() {
  jq -r '.browserTest.required // true' "$LOOP_CONFIG"
}

write_skipped_report() {
  local reason="$1"
  local report
  report="$(jq -n \
    --arg slice "$SLICE_ID" \
    --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg reason "$reason" \
    '{slice: $slice, timestamp: $ts, pass: true, skipped: true, reason: $reason}')"
  write_run_report "${RID}-browser-test.json" "$report"
  echo "$report"
}

write_browser_test_report() {
  local test_pass="$1"
  local timed_out="$2"
  local timeout_reason="$3"
  local agent_status="$4"
  local phases_json="$5"

  jq -n \
    --arg slice "$SLICE_ID" \
    --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --argjson pass "$test_pass" \
    --argjson skipped false \
    --argjson timedOut "$timed_out" \
    --arg reason "$timeout_reason" \
    --arg agentStatus "$agent_status" \
    --argjson phases "$phases_json" \
    '{slice: $slice, timestamp: $ts, pass: $pass, skipped: $skipped, timedOut: $timedOut, reason: (if $reason == "" then null else $reason end), agentExitCode: ($agentStatus | tonumber), phases: $phases}'
}

append_phase_result() {
  local phases_json="$1"
  local phase="$2"
  local pass="$3"
  local prior_run_id="${4:-}"
  local case_ids_json="${5:-[]}"
  jq -n \
    --argjson phases "$phases_json" \
    --arg name "$phase" \
    --argjson pass "$pass" \
    --arg prior "$prior_run_id" \
    --argjson caseIds "$case_ids_json" \
    '$phases + [{
      name: $name,
      pass: $pass,
      priorRunId: (if $prior == "" then null else $prior end),
      caseIds: (if ($caseIds | length) == 0 then null else $caseIds end)
    }]'
}

if ! slice_requires_browser_test "$SLICE_ID"; then
  echo "==> Browser test skipped (agent not in activeWhenAgent): ${SLICE_ID}"
  write_skipped_report "agent not in browserTest.activeWhenAgent"
  exit 0
fi

if [[ "$(browser_test_required)" != "true" ]]; then
  echo "==> Browser test skipped (browserTest.required=false)"
  write_skipped_report "browserTest.required is false"
  exit 0
fi

cleanup_playwright_mcp_artifacts
ensure_screenshot_dir "$(screenshot_dir_for_slice "$SLICE_ID" browser-test)"
ensure_playwright_regression_dirs "$SLICE_ID" "$RID"

require_preview="$(jq -r '.browserTest.requirePreviewStack // true' "$LOOP_CONFIG")"
if [[ "$require_preview" == "true" ]]; then
  echo "==> Verifying preview stack before browser test"
  set +e
  ensure_preview_stack_for_browser_test
  stack_status=$?
  set -e
  if [[ "$stack_status" -ne 0 ]]; then
    report="$(jq -n \
      --arg slice "$SLICE_ID" \
      --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
      '{slice: $slice, timestamp: $ts, pass: false, skipped: false, reason: "preview stack verification failed"}')"
    write_run_report "${RID}-browser-test.json" "$report"
    exit 1
  fi
fi

base_prompt="$(./ai-harness/scripts/build-prompt.sh "$SLICE_ID" tester)"

changed_files=""
checks_summary=""
artifacts_list=""
acceptance_tags=""
slice_json="$(get_slice_json "$SLICE_ID")"

if git rev-parse --git-dir >/dev/null 2>&1; then
  changed_files="$(git_changed_files | sed 's/^/- /')"
fi

checks_summary="$(find_checks_report_for_slice "$SLICE_ID" "$RUN_ID")"
artifacts_list="$(echo "$slice_json" | jq -r '.completionArtifacts[]? | "- " + .' 2>/dev/null || true)"
acceptance_tags="$(echo "$slice_json" | jq -r '.acceptance[]? | "- " + .' 2>/dev/null || true)"

generated_browser_cases=""
test_cases_json=""
if slice_test_cases_current "$SLICE_ID"; then
  test_cases_json="$(load_test_cases_json_for_slice "$SLICE_ID" | jq -c '.')"
  generated_browser_cases="$(load_test_cases_json_for_slice "$SLICE_ID" | jq -r '
    .cases[]? | select(.layer == "browser")
    | "- **\(.id)** [\(.category)/\(.priority)]: \(.title)"
      + (if .harnessSkip then "\n  **Harness scope: SKIP \(.harnessSkip)** — do not mark FAIL; report SKIP with this reason tag" else "" end)
      + "\n  Product: \(.traceability | join(", "))\n  Preconditions: \(.preconditions | join("; "))\n  Steps: \(.steps | join(" → "))\n  Expected: \(.expected)"
  ' 2>/dev/null || true)"
fi

WEB_PORT="$(aih_web_port)"
API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
MODEL="$(get_model tester)"

build_phase_prompt() {
  local phase="$1"
  local cases_block="$2"
  local phase_instruction="$3"

  printf '%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n' \
    "$base_prompt" \
    "## Harness reminder

Computational checks already passed. Use **Playwright MCP** to verify acceptance criteria in the browser. Do not edit files or re-run npm test/build scripts." \
    "$phase_instruction" \
    "## Preview stack

- Web: http://localhost:${WEB_PORT}
- API health: http://localhost:${API_PORT}/api/v1/health
- Dev auth: see docs/technical/10-local-development-setup.md" \
    "## Changed files (context only — do not edit)

${changed_files:-_(none detected)_}" \
    "## Completion artifacts

${artifacts_list:-_(none listed)_}" \
    "## Slice acceptance tags (derive browser scenarios from artifacts when no browser cases below)

${acceptance_tags:-_(none listed)_}" \
    "## Generated browser test cases (${phase} phase — mandatory checklist)

${cases_block:-_(no browser-layer cases in current artifacts for this slice — derive scenarios from acceptance tags, slice description, and docs above)_}" \
    "## Full test case artifact (reference)

\`\`\`json
${test_cases_json:-{}}
\`\`\`" \
    "## Computational checks (already passed — trust this)

\`\`\`json
${checks_summary}
\`\`\`"
}

# Returns: sets globals PHASE_PASS, PHASE_TIMED_OUT, PHASE_TIMEOUT_REASON, PHASE_AGENT_STATUS
run_browser_test_phase() {
  local phase="$1"
  local fail_fast="$2"
  local prior_run_id="${3:-}"
  shift 3
  local -a case_ids=("$@")

  local cases_block=""
  local phase_instruction=""
  local case_ids_json="[]"

  if [[ "$phase" == "retry" ]]; then
    cases_block="$(filter_browser_cases_prompt_block "$SLICE_ID" "${case_ids[@]}" 2>/dev/null || true)"
    case_ids_json="$(printf '%s\n' "${case_ids[@]}" | jq -R . | jq -s .)"
    phase_instruction="## Retry phase — failed cases from prior run

Prior failed run: \`${prior_run_id}\`

**Retry-only pass.** Execute **only** the browser cases listed below (failed in the prior run). Ignore all other cases in the artifact for this invocation.

- On the **first** \`FAIL\` among these cases: report it, emit \`BROWSER_TEST_FAIL\`, and **stop** — do not run remaining retry cases (\`SKIP\` cases do not count as failures; continue past them)
- When **all** listed runnable cases PASS (or SKIP): emit \`BROWSER_TEST_PASS\` (the harness will run a separate full verification phase next)

Per-action 30s timeouts still apply; fail-fast means stop the **case list**, not abandon a stuck step before its timeout."
  else
    cases_block="$generated_browser_cases"
    local codegen_block
    codegen_block="$(format_playwright_codegen_block "$SLICE_ID" "$RID")"
    phase_instruction="## Full verification phase

Execute **every** \`layer: browser\` case from the generated test case artifact (or derive from acceptance tags when none are listed). Report PASS, FAIL, or SKIP per case \`id\`. Mark physical-device or not-applicable cases as \`SKIP\` (see prompt).

${codegen_block}

Emit \`BROWSER_TEST_PASS\` only when all runnable cases pass **and** no P0/P1 UX bugs remain."
  fi

  local full_prompt
  full_prompt="$(build_phase_prompt "$phase" "$cases_block" "$phase_instruction")"
  local outfile="${RUNS_DIR}/${RID}-browser-test-${phase}.txt"

  aih_step "Running browser test agent — ${phase} phase (${AGENT_BIN}, model=${MODEL})"
  aih_agent_begin "tester ${phase} (${MODEL})"
  set +e
  agent_invoke_browser_test "$MODEL" "$full_prompt" "$outfile"
  PHASE_AGENT_STATUS=$?
  set -e
  aih_agent_end "${PHASE_AGENT_STATUS}"

  local test_text
  test_text="$(cat "$outfile")"
  if ! agent_stream_enabled; then
    echo "$test_text"
  fi

  PHASE_PASS=false
  if ! browser_output_has_actionable_failures "$outfile"; then
    if grep -qE 'TC-[A-Z0-9][A-Z0-9-]*:[[:space:]]*(PASS|SKIP|FAIL)' "$outfile" 2>/dev/null \
        || echo "$test_text" | grep -q 'BROWSER_TEST_PASS'; then
      if [[ "$phase" == "full" ]] && browser_output_has_ux_blockers "$outfile"; then
        PHASE_PASS=false
        echo "==> Phase validation failed: P0/P1 UX bugs block pass" >&2
      else
        PHASE_PASS=true
      fi
    fi
  else
    echo "==> Phase validation failed: output contains FAIL or UX P0/P1 lines" >&2
  fi

  if [[ "$phase" == "retry" && ${#case_ids[@]} -gt 0 ]]; then
    if ! browser_case_ids_still_failing_in_output "$outfile" "${case_ids[@]}"; then
      PHASE_PASS=false
      echo "==> Retry phase validation failed: case output still contains FAIL lines" >&2
    fi
  fi

  PHASE_TIMED_OUT=false
  PHASE_TIMEOUT_REASON=""
  if [[ "$PHASE_AGENT_STATUS" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
    PHASE_TIMED_OUT=true
    local timeout_ms
    timeout_ms="$(get_agent_timeout_ms "$LOOP_CONFIG")"
    PHASE_TIMEOUT_REASON="Agent timed out after ${timeout_ms}ms"
    PHASE_PASS=false
  fi

  if [[ "$PHASE_PASS" == true && "$PHASE_AGENT_STATUS" -eq 0 ]]; then
    return 0
  fi
  return 1
}

PHASES_JSON='[]'
FINAL_PASS=true
FINAL_TIMED_OUT=false
FINAL_TIMEOUT_REASON=""
FINAL_AGENT_STATUS=0

retry_ids=()
prior_run=""
if [[ "$(browser_test_retry_failed_cases_first)" == "true" ]]; then
  if prior_run="$(find_latest_failed_run_id_for_slice "$SLICE_ID" browser-test 2>/dev/null)"; then
    while IFS= read -r case_id; do
      [[ -z "$case_id" ]] && continue
      retry_ids+=("$case_id")
    done < <(extract_failed_browser_case_ids "$prior_run" 2>/dev/null || true)
  fi
fi

if ((${#retry_ids[@]} > 0)); then
  if ! run_browser_test_phase retry true "$prior_run" "${retry_ids[@]}"; then
    FINAL_PASS=false
    FINAL_TIMED_OUT="$PHASE_TIMED_OUT"
    FINAL_TIMEOUT_REASON="$PHASE_TIMEOUT_REASON"
    FINAL_AGENT_STATUS="$PHASE_AGENT_STATUS"
  fi
  retry_case_ids_json="$(printf '%s\n' "${retry_ids[@]}" | jq -R . | jq -s .)"
  PHASES_JSON="$(append_phase_result "$PHASES_JSON" retry "$PHASE_PASS" "$prior_run" "$retry_case_ids_json")"

  if [[ "$PHASE_PASS" != true ]]; then
    combined_outfile="${RUNS_DIR}/${RID}-browser-test.txt"
    {
      echo "# Browser test — retry phase (failed)"
      echo ""
      cat "${RUNS_DIR}/${RID}-browser-test-retry.txt"
    } >"$combined_outfile"

    report="$(write_browser_test_report false "$FINAL_TIMED_OUT" "$FINAL_TIMEOUT_REASON" "$FINAL_AGENT_STATUS" "$PHASES_JSON")"
    report="$(enrich_browser_test_report_json "$report" "$combined_outfile" "$SLICE_ID" "$RID")"
    write_run_report "${RID}-browser-test.json" "$report"
    exit 1
  fi
fi

if run_browser_test_phase full false; then
  :
else
  FINAL_PASS=false
  FINAL_TIMED_OUT="$PHASE_TIMED_OUT"
  FINAL_TIMEOUT_REASON="$PHASE_TIMEOUT_REASON"
  FINAL_AGENT_STATUS="$PHASE_AGENT_STATUS"
fi
PHASES_JSON="$(append_phase_result "$PHASES_JSON" full "$PHASE_PASS" "" "[]")"

combined_outfile="${RUNS_DIR}/${RID}-browser-test.txt"
{
  if [[ -f "${RUNS_DIR}/${RID}-browser-test-retry.txt" ]]; then
    echo "# Browser test — retry phase"
    echo ""
    cat "${RUNS_DIR}/${RID}-browser-test-retry.txt"
    echo ""
    echo "---"
    echo ""
  fi
  echo "# Browser test — full phase"
  echo ""
  cat "${RUNS_DIR}/${RID}-browser-test-full.txt"
} >"$combined_outfile"

if [[ "$PHASE_PASS" != true ]]; then
  FINAL_PASS=false
fi

report="$(write_browser_test_report "$FINAL_PASS" "$FINAL_TIMED_OUT" "$FINAL_TIMEOUT_REASON" "$FINAL_AGENT_STATUS" "$PHASES_JSON")"
report="$(enrich_browser_test_report_json "$report" "$combined_outfile" "$SLICE_ID" "$RID")"
write_run_report "${RID}-browser-test.json" "$report"

if [[ "$FINAL_PASS" == true ]]; then
  if parse_line="$(parse_playwright_regression_from_output "$combined_outfile" 2>/dev/null)"; then
    spec_path="$(echo "$parse_line" | cut -f1)"
    test_count="$(jq_number_or_default "$(echo "$parse_line" | cut -f2)")"
    tc_ids_json="$(jq_json_or_default "$(extract_source_tc_ids_from_output "$combined_outfile" | jq -R . | jq -s . 2>/dev/null || true)" '[]')"
    update_playwright_regression_index "$SLICE_ID" "$spec_path" "$RID" "$test_count" "$tc_ids_json"
  fi
  git_commit_browser_test_pass "$SLICE_ID" "$RID"
  exit 0
fi
exit 1
