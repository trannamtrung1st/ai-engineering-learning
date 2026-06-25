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

# --- Implement ---
if [[ "${AIH_SKIP_AGENT:-}" == "1" ]]; then
  echo "WARN: AIH_SKIP_AGENT=1 — skipping implementer agent"
  agent_out="${RUNS_DIR}/${RID}-agent.txt"
  echo "SLICE_DONE ${SLICE_ID}" > "$agent_out"
else
  require_agent
  prompt="$(./ai-harness/scripts/build-prompt.sh "$SLICE_ID" implementer)"
  model="$(get_model default)"
  agent_out="${RUNS_DIR}/${RID}-agent.txt"
  echo "==> Running implementer (${AGENT_BIN}, model=${model})"
  set +e
  agent_invoke "$model" "$prompt" "$agent_out"
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

# --- AI review ---
if [[ "${AIH_SKIP_REVIEW:-}" == "1" ]]; then
  echo "WARN: AIH_SKIP_REVIEW=1 — skipping AI review"
else
  echo "==> Running AI code review"
  set +e
  ./ai-harness/scripts/run-ai-review.sh "$SLICE_ID"
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
