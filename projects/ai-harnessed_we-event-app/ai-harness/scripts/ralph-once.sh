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

echo "==> Ralph iteration: slice=${SLICE_ID}"

RID="$(run_id)"
ensure_runs_dir

# --- Test case drift ---
drift_failed=false
while IFS= read -r ref; do
  [[ -z "$ref" ]] && continue
  set +e
  ./ai-harness/scripts/check-test-case-drift.sh "$ref" 2>&1
  ref_drift=$?
  set -e
  if [[ "$ref_drift" -ne 0 ]]; then
    drift_failed=true
  fi
done < <(slice_product_item_refs "$SLICE_ID")
if [[ "$drift_failed" == true ]]; then
  echo "==> Doc drift detected for product items referenced by ${SLICE_ID} — run: npm run aih:testgen:loop"
  exit 1
fi

# --- Test case gate ---
if ! slice_test_cases_current "$SLICE_ID"; then
  gate_mode="$(test_case_gate_mode)"
  if [[ "$gate_mode" == "required" ]]; then
    echo "ERROR: test cases not current for all product items referenced by slice ${SLICE_ID}" >&2
    echo "Missing items — run: npm run aih:testgen:loop" >&2
    echo "Skip gate: AIH_SKIP_TESTGEN_GATE=1" >&2
    exit 1
  fi
  missing_tags="$(slice_missing_test_case_tags "$SLICE_ID" | tr '\n' ', ' | sed 's/, $//')"
  echo "WARN: test cases not current for slice ${SLICE_ID} — continuing (mode=${gate_mode})"
  echo "WARN: missing tags: ${missing_tags:-_(none listed)_}"
  echo "WARN: harness will re-queue for verification when TestGen completes"
fi

# --- Implement ---
skip_implementer=false
if [[ "${AIH_SKIP_AGENT:-}" == "1" ]]; then
  skip_implementer=true
elif slice_reverify_only "$SLICE_ID"; then
  echo "==> Re-verification only (test cases now available)"
  skip_implementer=true
fi

if [[ "$skip_implementer" == true ]]; then
  if [[ "${AIH_SKIP_AGENT:-}" == "1" ]]; then
    echo "WARN: AIH_SKIP_AGENT=1 — skipping implementer agent"
  fi
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
  echo "==> Running implementer (${AGENT_BIN}, model=${model})"
  set +e
  agent_invoke "$model" "$prompt" "$agent_out" "$SLICE_ID"
  agent_status=$?
  set -e
  echo "==> Agent exit: ${agent_status}"
fi

agent_text="$(cat "$agent_out")"
if echo "$agent_text" | grep -q "SLICE_BLOCKED"; then
  reason="$(echo "$agent_text" | grep "SLICE_BLOCKED" | tail -1)"
  append_guardrail "$SLICE_ID" "$reason"
  append_progress "$SLICE_ID" "blocked"
  echo "Slice blocked. See guardrails.md"
  exit 1
fi

# --- Computational checks ---
echo "==> Running computational checks"
set +e
check_out="$(./ai-harness/scripts/run-checks.sh "$SLICE_ID" 2>&1)"
check_status=$?
set -e
echo "$check_out"

if [[ "$check_status" -ne 0 ]]; then
  append_guardrail "$SLICE_ID" "Computational checks failed — see ${RID}-checks.json"
  append_progress "$SLICE_ID" "checks_failed"
  exit 1
fi

# --- Browser functional test (Playwright MCP) ---
if [[ "${AIH_SKIP_BROWSER_TEST:-}" != "1" ]]; then
  echo "==> Running browser functional test (Playwright MCP)"
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
  echo "WARN: AIH_SKIP_REVIEW=1 — skipping AI review"
else
  echo "==> Running AI code review (read-only static pass)"
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
  echo ""
  echo "==> HUMAN REVIEW REQUIRED for merge-ready slice: ${SLICE_ID}"
  echo "    Complete: ai-harness/workflows/human-review-checklist.md"
  echo "    Sign-off: HUMAN_REVIEW_PASS ${SLICE_ID}"
fi

if all_slices_pass; then
  echo "COMPLETE"
else
  echo "Slice ${SLICE_ID} passed. Next: $(pick_next_slice_id)"
fi
