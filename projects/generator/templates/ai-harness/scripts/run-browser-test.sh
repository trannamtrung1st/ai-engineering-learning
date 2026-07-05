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

browser_test_exit_failure() {
  local outfile="${1:-}"
  local spec_path=""
  if [[ -n "$outfile" && -f "$outfile" ]]; then
    if parse_line="$(parse_playwright_regression_from_output "$outfile" 2>/dev/null)"; then
      spec_path="$(echo "$parse_line" | cut -f1)"
    fi
  fi
  revert_browser_test_workspace_changes "$SLICE_ID" "$RID" "$spec_path"
  exit 1
}

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

write_combined_browser_test_outfile() {
  local combined_outfile="${RUNS_DIR}/${RID}-browser-test.txt"
  local first=true
  {
    for section in "${BROWSER_TEST_COMBINED_SECTIONS[@]}"; do
      local label="${section%%|*}"
      local path="${section#*|}"
      [[ -f "$path" ]] || continue
      if [[ "$first" != true ]]; then
        echo "---"
        echo ""
      fi
      first=false
      echo "# Browser test — ${label}"
      echo ""
      cat "$path"
      echo ""
    done
  } >"$combined_outfile"
  echo "$combined_outfile"
}

record_browser_test_failure() {
  local combined_outfile="$1"
  local report
  report="$(write_browser_test_report false "$FINAL_TIMED_OUT" "$FINAL_TIMEOUT_REASON" "$FINAL_AGENT_STATUS" "$PHASES_JSON")"
  report="$(enrich_browser_test_report_json "$report" "$combined_outfile" "$SLICE_ID" "$RID")"
  write_run_report "${RID}-browser-test.json" "$report"
  browser_test_exit_failure "$combined_outfile"
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

if integration_gate_blocks_browser_test "$SLICE_ID"; then
  echo "==> Browser test blocked — phase 4 integration debt pending"
  handle_integration_gate_browser_block "$SLICE_ID" "$RID"
  exit 1
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
    browser_test_exit_failure
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

common_ui_ux_cases=""
common_ui_ux_blocking=""
if [[ "$(common_ui_ux_suite_enabled)" == "true" ]]; then
  common_ui_ux_cases="$(format_common_ui_ux_suite_block 2>/dev/null || true)"
  common_ui_ux_blocking="$(common_ui_ux_suite_blocking_priorities_json | jq -r 'join("/")' 2>/dev/null || echo "P0/P1")"
fi

WEB_PORT="$(aih_web_port)"
API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
MODEL="$(get_model tester)"
MAX_CASES_PER_BATCH="$(browser_test_max_cases_per_batch)"
BATCHING_ENABLED=false
if browser_test_batching_enabled; then
  BATCHING_ENABLED=true
fi

build_phase_prompt() {
  local phase_kind="$1"
  local cases_block="$2"
  local phase_instruction="$3"
  local prior_batch_summary="${4:-}"

  local common_suite_section=""
  if [[ "$phase_kind" == "finalize" && -n "$common_ui_ux_cases" ]]; then
    common_suite_section="## Common UI/UX suite (always executed — generic, product-wide)

Run **every** case below against **every distinct screen/state** exercised in prior batches. These are generic UI/UX checks — not tied to any requirement tag.

- Report each as \`TC-UX-COMMON-NNN: PASS|FAIL|SKIP\` with brief evidence and a screenshot path.
- Mark \`SKIP\` only when the case genuinely does not apply to any screen in this slice (e.g. no forms in scope) — never to avoid a defect.
- **Gating:** a \`FAIL\` on a **${common_ui_ux_blocking:-P0/P1}** case blocks \`BROWSER_TEST_PASS\`. Lower-priority FAILs do not block on their own — log each as a \`UX-<slice-id>-NNN\` defect (advisory) per \`ai-harness/docs/ux-bug-logging.md\`.

${common_ui_ux_cases}"
  fi

  local prior_summary_section=""
  if [[ -n "$prior_batch_summary" ]]; then
    prior_summary_section="$prior_batch_summary"
  fi

  printf '%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n' \
    "$base_prompt" \
    "## Harness reminder

Computational checks already passed. Use **Playwright MCP** to verify acceptance criteria in the browser. Do not edit files or re-run npm test/build scripts." \
    "$phase_instruction" \
    "${prior_summary_section}" \
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
    "## Generated browser test cases (${phase_kind} phase — mandatory checklist)

${cases_block:-_(no browser-layer cases in current artifacts for this slice — derive scenarios from acceptance tags, slice description, and docs above)_}" \
    "${common_suite_section}" \
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
# phase_kind: retry | batch | finalize | full
run_browser_test_phase() {
  local phase_name="$1"
  local phase_kind="$2"
  local prior_run_id="${3:-}"
  local batch_index="${4:-0}"
  local batch_total="${5:-0}"
  local prior_batch_summary="${6:-}"
  shift 6
  local -a case_ids=("$@")

  local cases_block=""
  local phase_instruction=""
  local case_ids_json="[]"

  if [[ "$phase_kind" == "retry" ]]; then
    cases_block="$(filter_browser_cases_prompt_block "$SLICE_ID" "${case_ids[@]}" 2>/dev/null || true)"
    case_ids_json="$(printf '%s\n' "${case_ids[@]}" | jq -R . | jq -s .)"
    if [[ "$batch_total" -gt 1 ]]; then
      phase_instruction="## Retry batch ${batch_index} of ${batch_total} — failed cases from prior run

Prior failed run: \`${prior_run_id}\`

**Retry-only pass.** Execute **only** the browser cases listed below (failed in the prior run). Ignore all other cases in the artifact for this invocation.

- Run **every** listed case — do not stop after the first failure. Collect **all** FAIL results before emitting the final signal.
- Do **not** run common UI/UX suite, UX audit, test-case maintenance, or Playwright codegen
- When **all** listed runnable cases PASS (or SKIP): emit \`BROWSER_TEST_BATCH_PASS\`
- When **any** runnable case FAILs: emit \`BROWSER_TEST_FAIL\` with the **complete** blocker list at the end

Per-action 30s timeouts still apply. Complete the full case list within the pass budget."
    else
      phase_instruction="## Retry phase — failed cases from prior run

Prior failed run: \`${prior_run_id}\`

**Retry-only pass.** Execute **only** the browser cases listed below (failed in the prior run). Ignore all other cases in the artifact for this invocation.

- Run **every** listed case — do not stop after the first failure. Collect **all** FAIL results before emitting the final signal.
- Do **not** run common UI/UX suite, UX audit, test-case maintenance, or Playwright codegen
- When **all** listed runnable cases PASS (or SKIP): emit \`BROWSER_TEST_BATCH_PASS\` (the harness runs case batches or finalize next)
- When **any** runnable case FAILs: emit \`BROWSER_TEST_FAIL\` with the **complete** blocker list at the end

Per-action 30s timeouts still apply. Complete the full case list within the pass budget."
    fi
  elif [[ "$phase_kind" == "batch" ]]; then
    cases_block="$(filter_browser_cases_prompt_block "$SLICE_ID" "${case_ids[@]}" 2>/dev/null || true)"
    case_ids_json="$(printf '%s\n' "${case_ids[@]}" | jq -R . | jq -s .)"
    phase_instruction="## Case batch ${batch_index} of ${batch_total} — execute ONLY these case IDs

Execute **only** the browser cases listed below. Ignore all other cases in the artifact for this invocation.

- Run **every** listed case — collect **all** FAIL results before emitting the final signal
- Do **not** run common UI/UX suite, UX audit, test-case maintenance, or Playwright codegen
- When **all** listed runnable cases PASS (or SKIP): emit \`BROWSER_TEST_BATCH_PASS\`
- When **any** runnable case FAILs: emit \`BROWSER_TEST_FAIL\` with the **complete** blocker list at the end

Per-action 30s timeouts still apply. Complete the full case list within the pass budget."
  elif [[ "$phase_kind" == "finalize" ]]; then
    cases_block="_(Functional browser cases were executed in prior batches — do not re-run them. See prior batch summary above.)_"
    local codegen_block
    codegen_block="$(format_playwright_codegen_block "$SLICE_ID" "$RID")"
    phase_instruction="## Finalize phase — UX audit, test-case maintenance, and Playwright codegen

Functional \`layer: browser\` cases were already verified in prior batches. **Do not re-run** those cases.

1. Run the **common UI/UX suite** against every distinct screen/state exercised in prior batches
2. **App logo home shortcut** — on every authenticated screen visited, verify the app logo navigates to the role's home route
3. **UI/UX screen audit** — enumerate screens from prior batches + \`completionArtifacts\`; capture screenshots; run the 10-item checklist from \`ai-harness/docs/ui-visual-verification.md\`
4. Write \`{{UX_BUGS_PATH}}\` per schema before final signal
5. **Test case maintenance** — reconcile browser-layer cases in \`docs/test-cases/items/<tag>.json\`
6. **Playwright regression codegen** — update the slice spec from all exercised flows

${codegen_block}

Emit \`BROWSER_TEST_PASS\` only when common suite passes (no P0/P1 UX bugs), maintenance is done, and Playwright config/spec are ready for the harness regression check."
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
  full_prompt="$(build_phase_prompt "$phase_kind" "$cases_block" "$phase_instruction" "$prior_batch_summary")"
  local outfile="${RUNS_DIR}/${RID}-browser-test-${phase_name}.txt"

  aih_step "Running browser test agent — ${phase_name} (${AGENT_BIN}, model=${MODEL})"
  aih_agent_begin "tester ${phase_name} (${MODEL})"
  local browser_timeout_ms=""
  browser_timeout_ms="$(get_browser_test_timeout_ms "$SLICE_ID" 2>/dev/null || true)"
  if [[ -n "$browser_timeout_ms" ]]; then
    export AIH_AGENT_TIMEOUT_MS="$browser_timeout_ms"
  fi
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
        || echo "$test_text" | grep -qE 'BROWSER_TEST_(BATCH_)?PASS'; then
      if [[ "$phase_kind" == "finalize" || "$phase_kind" == "full" ]] && browser_output_has_ux_blockers "$outfile"; then
        PHASE_PASS=false
        echo "==> Phase validation failed: P0/P1 UX bugs block pass" >&2
      else
        PHASE_PASS=true
      fi
    elif [[ "$phase_kind" == "finalize" ]] && echo "$test_text" | grep -q 'BROWSER_TEST_PASS'; then
      PHASE_PASS=true
    fi
  else
    echo "==> Phase validation failed: output contains FAIL or UX P0/P1 lines" >&2
  fi

  if [[ ${#case_ids[@]} -gt 0 ]]; then
    if ! validate_batch_case_results "$outfile" "${case_ids[@]}"; then
      PHASE_PASS=false
      echo "==> Phase validation failed: assigned case results missing or still FAIL" >&2
    fi
  fi

  if [[ "$phase_kind" == "batch" || "$phase_kind" == "retry" ]]; then
    if [[ "$PHASE_PASS" == true ]] && ! browser_output_has_batch_pass_signal "$outfile"; then
      if ! echo "$test_text" | grep -q 'BROWSER_TEST_PASS'; then
        echo "==> Phase validation failed: missing BROWSER_TEST_BATCH_PASS signal" >&2
        PHASE_PASS=false
      fi
    fi
  fi

  PHASE_TIMED_OUT=false
  PHASE_TIMEOUT_REASON=""
  if [[ "$PHASE_AGENT_STATUS" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
    PHASE_TIMED_OUT=true
    local timeout_ms
    timeout_ms="$(get_browser_test_timeout_ms "$SLICE_ID" 2>/dev/null || get_agent_timeout_ms "$LOOP_CONFIG" "$SLICE_ID")"
    PHASE_TIMEOUT_REASON="Agent timed out after ${timeout_ms}ms"
    PHASE_PASS=false
  fi

  if [[ "$phase_kind" == "finalize" || "$phase_kind" == "full" ]] && [[ "$PHASE_PASS" == true ]]; then
    aih_step "Validating Playwright UI config before phase close"
    pw_log="${RUNS_DIR}/${RID}-browser-test-playwright.log"
    set +e
    verify_playwright_ui_for_browser_test_close "$SLICE_ID" "$outfile" "$pw_log"
    pw_verify_status=$?
    set -e
    if [[ "$pw_verify_status" -ne 0 ]]; then
      PHASE_PASS=false
      echo "==> Phase validation failed: Playwright UI config validation failed — see ${pw_log}" >&2
      {
        echo ""
        echo "## Playwright UI verification (harness — required before phase close)"
        echo ""
        cat "$pw_log" 2>/dev/null || echo "(no log)"
      } >>"$outfile"
    elif [[ -f "$pw_log" ]]; then
      {
        echo ""
        echo "## Playwright UI verification (harness — passed)"
        echo ""
        cat "$pw_log"
      } >>"$outfile"
    fi
  fi

  if [[ "$phase_kind" == "finalize" || "$phase_kind" == "full" ]]; then
    if [[ "$PHASE_PASS" == true ]] && ! echo "$test_text" | grep -q 'BROWSER_TEST_PASS'; then
      echo "==> Phase validation failed: missing BROWSER_TEST_PASS signal" >&2
      PHASE_PASS=false
    fi
  fi

  if [[ "$PHASE_PASS" == true && "$PHASE_AGENT_STATUS" -eq 0 ]]; then
    return 0
  fi
  return 1
}

run_case_id_batches() {
  local phase_prefix="$1"
  local prior_run_id="${2:-}"
  local -a all_case_ids=("${@:3}")
  local -a batch_outfiles=()
  local batch_json batch_index=0 batch_total=0
  local -a batch_arrays=()

  if ((${#all_case_ids[@]} == 0)); then
    return 0
  fi

  if [[ "$BATCHING_ENABLED" == true ]] && ((${#all_case_ids[@]} > MAX_CASES_PER_BATCH)); then
    while IFS= read -r batch_json; do
      [[ -z "$batch_json" ]] && continue
      batch_arrays+=("$batch_json")
    done < <(split_case_ids_into_batches "$MAX_CASES_PER_BATCH" "${all_case_ids[@]}")
    batch_total="${#batch_arrays[@]}"
  else
    batch_arrays+=("$(printf '%s\n' "${all_case_ids[@]}" | jq -R . | jq -s .)")
    batch_total=1
  fi

  batch_index=0
  for batch_json in "${batch_arrays[@]}"; do
    batch_index=$((batch_index + 1))
    local -a batch_ids=()
    while IFS= read -r cid; do
      [[ -z "$cid" ]] && continue
      batch_ids+=("$cid")
    done < <(jq -r '.[]' <<< "$batch_json")

    local phase_name="${phase_prefix}"
    if [[ "$batch_total" -gt 1 ]]; then
      phase_name="${phase_prefix}-${batch_index}"
    fi

    local phase_kind="$phase_prefix"
    if [[ "$phase_prefix" == "retry" ]]; then
      phase_kind="retry"
    elif [[ "$phase_prefix" == "batch" ]]; then
      phase_kind="batch"
    fi

    if ! run_browser_test_phase "$phase_name" "$phase_kind" "$prior_run_id" "$batch_index" "$batch_total" "" "${batch_ids[@]}"; then
      FINAL_PASS=false
      FINAL_TIMED_OUT="$PHASE_TIMED_OUT"
      FINAL_TIMEOUT_REASON="$PHASE_TIMEOUT_REASON"
      FINAL_AGENT_STATUS="$PHASE_AGENT_STATUS"
      return 1
    fi

    local outfile="${RUNS_DIR}/${RID}-browser-test-${phase_name}.txt"
    batch_outfiles+=("$outfile")
    BROWSER_TEST_COMBINED_SECTIONS+=("${phase_name}|${outfile}")

    local batch_case_ids_json
    batch_case_ids_json="$(printf '%s\n' "${batch_ids[@]}" | jq -R . | jq -s .)"
    if [[ "$phase_prefix" == "retry" ]]; then
      if [[ "$batch_total" -gt 1 ]]; then
        PHASES_JSON="$(append_batch_phase_result "$PHASES_JSON" "$phase_name" "$PHASE_PASS" "$batch_index" "$batch_total" "$prior_run_id" "$batch_case_ids_json")"
      else
        PHASES_JSON="$(append_phase_result "$PHASES_JSON" retry "$PHASE_PASS" "$prior_run_id" "$batch_case_ids_json")"
      fi
    else
      PHASES_JSON="$(append_batch_phase_result "$PHASES_JSON" "$phase_name" "$PHASE_PASS" "$batch_index" "$batch_total" "" "$batch_case_ids_json")"
    fi
  done

  PRIOR_BATCH_OUTFILES+=("${batch_outfiles[@]}")
  return 0
}

PHASES_JSON='[]'
FINAL_PASS=true
FINAL_TIMED_OUT=false
FINAL_TIMEOUT_REASON=""
FINAL_AGENT_STATUS=0
BROWSER_TEST_COMBINED_SECTIONS=()
PRIOR_BATCH_OUTFILES=()

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
  if ! run_case_id_batches retry "$prior_run" "${retry_ids[@]}"; then
    combined_outfile="$(write_combined_browser_test_outfile)"
    record_browser_test_failure "$combined_outfile"
  fi

  if [[ "$PHASE_PASS" != true ]]; then
    combined_outfile="$(write_combined_browser_test_outfile)"
    record_browser_test_failure "$combined_outfile"
  fi
fi

if [[ "$BATCHING_ENABLED" == true ]]; then
  runnable_ids=()
  while IFS= read -r case_id; do
    [[ -z "$case_id" ]] && continue
    runnable_ids+=("$case_id")
  done < <(list_runnable_browser_case_ids_for_slice "$SLICE_ID" 2>/dev/null || true)

  if ((${#runnable_ids[@]} > 0)); then
    if ! run_case_id_batches batch "" "${runnable_ids[@]}"; then
      combined_outfile="$(write_combined_browser_test_outfile)"
      record_browser_test_failure "$combined_outfile"
    fi
    if [[ "$PHASE_PASS" != true ]]; then
      combined_outfile="$(write_combined_browser_test_outfile)"
      record_browser_test_failure "$combined_outfile"
    fi
  fi

  prior_batch_summary=""
  if ((${#PRIOR_BATCH_OUTFILES[@]} > 0)); then
    prior_batch_summary="$(format_prior_batch_summary_block "${PRIOR_BATCH_OUTFILES[@]}")"
  fi
  if ! run_browser_test_phase finalize finalize "" 0 0 "$prior_batch_summary"; then
    FINAL_PASS=false
    FINAL_TIMED_OUT="$PHASE_TIMED_OUT"
    FINAL_TIMEOUT_REASON="$PHASE_TIMEOUT_REASON"
    FINAL_AGENT_STATUS="$PHASE_AGENT_STATUS"
  fi
  BROWSER_TEST_COMBINED_SECTIONS+=("finalize|${RUNS_DIR}/${RID}-browser-test-finalize.txt")
  PHASES_JSON="$(append_phase_result "$PHASES_JSON" finalize "$PHASE_PASS" "" "[]")"
else
  if ! run_browser_test_phase full full "" 0 0 ""; then
    FINAL_PASS=false
    FINAL_TIMED_OUT="$PHASE_TIMED_OUT"
    FINAL_TIMEOUT_REASON="$PHASE_TIMEOUT_REASON"
    FINAL_AGENT_STATUS="$PHASE_AGENT_STATUS"
  fi
  BROWSER_TEST_COMBINED_SECTIONS+=("full phase|${RUNS_DIR}/${RID}-browser-test-full.txt")
  PHASES_JSON="$(append_phase_result "$PHASES_JSON" full "$PHASE_PASS" "" "[]")"
fi

combined_outfile="$(write_combined_browser_test_outfile)"

if [[ "$PHASE_PASS" != true ]]; then
  FINAL_PASS=false
fi

report="$(write_browser_test_report "$FINAL_PASS" "$FINAL_TIMED_OUT" "$FINAL_TIMEOUT_REASON" "$FINAL_AGENT_STATUS" "$PHASES_JSON")"
report="$(enrich_browser_test_report_json "$report" "$combined_outfile" "$SLICE_ID" "$RID")"
write_run_report "${RID}-browser-test.json" "$report"

if [[ "$FINAL_PASS" == true ]]; then
  spec_path=""
  test_count=0
  if parse_line="$(resolve_playwright_regression_for_pass "$SLICE_ID" "$combined_outfile" 2>/dev/null)"; then
    spec_path="$(echo "$parse_line" | cut -f1)"
    test_count="$(jq_number_or_default "$(echo "$parse_line" | cut -f2)")"
    tc_ids_json="$(jq_json_or_default "$(extract_source_tc_ids_from_output "$combined_outfile" | jq -R . | jq -s . 2>/dev/null || true)" '[]')"
    sync_playwright_spec_to_backlog "$SLICE_ID" "$spec_path"
    update_playwright_regression_index "$SLICE_ID" "$spec_path" "$RID" "$test_count" "$tc_ids_json"
  else
    aih_err "BROWSER_TEST_PASS without playwright-regression line — browser tester must emit playwright-regression: <spec> (N tests)"
    browser_test_exit_failure "$combined_outfile"
  fi
  if [[ "${AIH_DEFER_BROWSER_TEST_COMMIT:-}" == "1" ]]; then
    aih_ok "Browser test passed — Playwright regression commit deferred until headless gate"
    exit 0
  fi
  if slice_requires_playwright_regression_gate "$SLICE_ID"; then
    aih_step "Running Playwright UI regression check (post browser test)"
    set +e
    ./ai-harness/scripts/run-checks.sh "$SLICE_ID" --playwright-only
    playwright_status=$?
    set -e
    if [[ "$playwright_status" -ne 0 ]]; then
      browser_test_exit_failure "$combined_outfile"
    fi
  fi
  set +e
  finalize_browser_test_pass "$SLICE_ID" "$RID" "$spec_path"
  finalize_status=$?
  set -e
  if [[ "$finalize_status" -ne 0 ]]; then
    browser_test_exit_failure "$combined_outfile"
  fi
  exit 0
fi
browser_test_exit_failure "$combined_outfile"
