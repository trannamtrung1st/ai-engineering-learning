#!/usr/bin/env bash
# Single Ralph iteration (implement → check → review → mark)
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

cd "$REPO_ROOT"

if all_slices_pass; then
  echo "COMPLETE"
  exit 0
fi

SLICE_ID="$(pick_next_slice_id)"
if [[ -z "$SLICE_ID" ]]; then
  echo "COMPLETE"
  exit 0
fi

aih_step "Ralph iteration: slice=${SLICE_ID}"

RID="$(run_id)"
ensure_runs_dir

# --- Test case drift ---
drift_failed=false
drift_checked=0
while IFS= read -r ref; do
  [[ -z "$ref" ]] && continue
  drift_checked=$((drift_checked + 1))
  set +e
  ./ai-harness/scripts/check-test-case-drift.sh --quiet "$ref" 2>&1
  ref_drift=$?
  set -e
  if [[ "$ref_drift" -ne 0 ]]; then
    drift_failed=true
  fi
done < <(slice_product_item_refs "$SLICE_ID")
if [[ "$drift_failed" == true ]]; then
  aih_err "Doc drift detected for product items referenced by ${SLICE_ID} — run: npm run aih:testgen:loop"
  exit 1
fi
if [[ "$drift_checked" -gt 0 ]]; then
  aih_ok "Doc drift check: ${drift_checked} tag(s) ok for ${SLICE_ID}"
fi

# --- Test case gate ---
if ! slice_test_cases_current "$SLICE_ID"; then
  gate_mode="$(test_case_gate_mode)"
  if [[ "$gate_mode" == "required" ]]; then
    aih_err "test cases not current for all product items referenced by slice ${SLICE_ID}"
    aih_err "Missing items — run: npm run aih:testgen:loop"
    aih_err "Skip gate: AIH_SKIP_TESTGEN_GATE=1"
    exit 1
  fi
  missing_tags="$(slice_missing_test_case_tags "$SLICE_ID" | tr '\n' ', ' | sed 's/, $//')"
  aih_warn "test cases not current for slice ${SLICE_ID} — continuing (mode=${gate_mode})"
  aih_warn "missing tags: ${missing_tags:-_(none listed)_}"
  aih_warn "set passes: false in whole-app-backlog.json to re-run after TestGen completes"
fi

# --- Implement ---
if [[ "${AIH_SKIP_AGENT:-}" == "1" ]]; then
  aih_warn "AIH_SKIP_AGENT=1 — skipping implementer agent"
  agent_out="${RUNS_DIR}/${RID}-agent.txt"
  echo "SLICE_DONE ${SLICE_ID}" > "$agent_out"
else
  require_agent
  prompt="$(./ai-harness/scripts/build-prompt.sh "$SLICE_ID" implementer)"
  model="$(get_model default)"
  agent_out="${RUNS_DIR}/${RID}-agent.txt"
  if slice_uses_browser_mcp "$SLICE_ID"; then
    cleanup_playwright_mcp_artifacts
  fi
  aih_step "Running implementer (${AGENT_BIN}, model=${model})"
  aih_agent_begin "implementer (${model})"
  set +e
  agent_invoke "$model" "$prompt" "$agent_out" "$SLICE_ID"
  agent_status=$?
  set -e
  aih_agent_end "${agent_status}"
fi

if [[ "${agent_status:-0}" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
  timeout_ms="$(get_agent_timeout_ms "$LOOP_CONFIG")"
  append_guardrail "$SLICE_ID" "Implementer agent timed out after ${timeout_ms}ms — see ${RID}-agent.txt"
  append_progress "$SLICE_ID" "agent_timeout"
  aih_err "Implementer agent timed out. See guardrails.md"
  exit 1
fi

agent_text="$(cat "$agent_out")"
if echo "$agent_text" | grep -q "SLICE_BLOCKED"; then
  reason="$(echo "$agent_text" | grep "SLICE_BLOCKED" | tail -1)"
  append_guardrail "$SLICE_ID" "$reason"
  append_progress "$SLICE_ID" "blocked"
  aih_err "Slice blocked. See guardrails.md"
  exit 1
fi

# --- Computational checks ---
aih_step "Running computational checks"
set +e
./ai-harness/scripts/run-checks.sh "$SLICE_ID"
check_status=$?
set -e

if [[ "$check_status" -ne 0 ]]; then
  append_guardrail "$SLICE_ID" "Computational checks failed — see ${RID}-checks.json"
  append_progress "$SLICE_ID" "checks_failed"
  exit 1
fi

# --- Browser functional test (Playwright MCP) ---
if [[ "${AIH_SKIP_BROWSER_TEST:-}" != "1" ]]; then
  aih_step "Running browser functional test (Playwright MCP)"
  set +e
  AIH_RUN_ID="$RID" ./ai-harness/scripts/run-browser-test.sh "$SLICE_ID" "$RID"
  browser_test_status=$?
  set -e
  if [[ "$browser_test_status" -ne 0 ]]; then
    append_guardrail "$SLICE_ID" "Browser test failed — see ${RID}-browser-test.json"
    append_progress "$SLICE_ID" "browser_test_failed"
    exit 1
  fi
fi

# --- AI review ---
if [[ "${AIH_SKIP_REVIEW:-}" == "1" ]]; then
  aih_warn "AIH_SKIP_REVIEW=1 — skipping AI review"
else
  aih_step "Running AI code review (read-only static pass)"
  set +e
  AIH_RUN_ID="$RID" ./ai-harness/scripts/run-ai-review.sh "$SLICE_ID" "$RID"
  review_status=$?
  set -e
  if [[ "$review_status" -ne 0 ]]; then
    append_guardrail "$SLICE_ID" "AI review failed — see ${RID}-review.json"
    append_progress "$SLICE_ID" "review_failed"
    exit 1
  fi
fi

# --- Mark pass ---
mark_slice_passed "$SLICE_ID"
append_progress "$SLICE_ID" "passed"

commit_on_pass="$(jq -r '.loop.commitOnPass // true' "$LOOP_CONFIG")"
if [[ "$commit_on_pass" == "true" ]] && git rev-parse --git-dir >/dev/null 2>&1; then
  if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    git add -A
    git commit -m "aih: complete slice ${SLICE_ID}" --no-verify 2>/dev/null || true
  fi
fi

merge_ready="$(get_slice_field "$SLICE_ID" mergeReady 2>/dev/null || echo "false")"
if [[ "$merge_ready" == "true" ]]; then
  aih_blank
  aih_section "HUMAN REVIEW REQUIRED: ${SLICE_ID}" alert
  aih_info "    Complete: ai-harness/workflows/human-review-checklist.md"
  aih_info "    Sign-off: HUMAN_REVIEW_PASS ${SLICE_ID}"
fi

if all_slices_pass; then
  echo "COMPLETE"
else
  aih_ok "Slice ${SLICE_ID} passed. Next: $(pick_next_slice_id)"
fi
