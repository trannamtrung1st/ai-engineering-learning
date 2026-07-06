#!/usr/bin/env bash
# Single generator iteration: agent/scaffold → verify → review → mark
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/gen-step.sh
source "$(dirname "$0")/lib/gen-step.sh"

require_gen_deps
cd "$REPO_ROOT"

discover_docs

if all_steps_pass; then
  echo "GEN_COMPLETE"
  exit 0
fi

STEP_ID="$(pick_next_step_id)"
if [[ -z "$STEP_ID" ]]; then
  echo "GEN_COMPLETE"
  exit 0
fi

gen_step "Generator iteration: step=${STEP_ID}"
RID="$(run_id)"
ensure_runs_dir

kind="$(get_step_field "$STEP_ID" kind)"

# --- Combined harness backlog: plan + JSON in one gen-loop iteration (separate agent sessions) ---
if should_run_harness_backlog_combined "$STEP_ID"; then
  assert_can_write_outputs
  if ! has_any_seed; then
    gen_err "No seed docs found under docs/ — add idea, BRD, design-system, or product-meta material"
    exit 1
  fi

  if ! run_harness_backlog_combined_iteration "$RID"; then
    exit 1
  fi

  commit_on_pass="$(jq -r '.loop.commitOnPass // true' "$LOOP_CONFIG")"
  if [[ "$commit_on_pass" == "true" ]] && git rev-parse --git-dir >/dev/null 2>&1; then
    if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
      git add -A
      git commit -m "gen: complete harness backlog (plan + JSON)" --no-verify 2>/dev/null || true
    fi
  fi

  if all_steps_pass; then
    echo "GEN_COMPLETE"
  else
    gen_ok "Harness backlog steps passed. Next: $(pick_next_step_id)"
  fi
  exit 0
fi

# --- Scaffold steps (no agent) ---
if [[ "$kind" == "scaffold" ]]; then
  assert_can_write_outputs
  case "$STEP_ID" in
    uiux-design-system)
      "${GEN_SCRIPTS_DIR}/emit-design-system.sh"
      ;;
    harness-scaffold)
      "${GEN_SCRIPTS_DIR}/emit-harness-scaffold.sh"
      ;;
    harness-customize-agents)
      "${GEN_SCRIPTS_DIR}/customize-harness-agents.sh"
      ;;
    repo-bootstrap)
      "${GEN_SCRIPTS_DIR}/emit-repo-bootstrap.sh"
      ;;
    *)
      gen_err "unknown scaffold step: $STEP_ID"
      exit 1
      ;;
  esac
fi

# --- Gate steps (verify only) ---
if [[ "$kind" == "gate" ]]; then
  gen_info "Gate step — running validators only"
fi

# --- Agent steps ---
if [[ "$kind" == "agent" ]]; then
  if [[ "$STEP_ID" != "input-validate" ]]; then
    assert_can_write_outputs
  fi

  if [[ "$STEP_ID" == "uiux-design-md" ]]; then
    "${GEN_SCRIPTS_DIR}/emit-design-md.sh"
  fi

  if ! has_any_seed; then
    gen_err "No seed docs found under docs/ — add idea, BRD, design-system, or product-meta material"
    exit 1
  fi

  if ! run_gen_agent_for_step "$STEP_ID" "$RID"; then
    exit 1
  fi
fi

# --- Verification ---
if ! run_gen_step_verify_with_self_fix "$STEP_ID" "$RID"; then
  exit 1
fi

if [[ "$kind" == "gate" ]]; then
  rm -f "${GEN_STATE_DIR}/last-gate-failure.txt"
  reset_gate_repair_count "$STEP_ID"
fi

# --- Optional AI review ---
review_required="$(jq -r '.aiReview.required // false' "$LOOP_CONFIG")"
if [[ "$review_required" == "true" && "$kind" == "agent" && "${GEN_SKIP_REVIEW:-}" != "1" ]]; then
  gen_step "Running doc review"
  set +e
  "${GEN_SCRIPTS_DIR}/run-doc-review.sh" "$STEP_ID" "$RID"
  review_status=$?
  set -e
  if [[ "$review_status" -ne 0 ]]; then
    append_progress "$STEP_ID" "review_failed"
    exit 1
  fi
fi

# --- Mark pass ---
mark_step_passed "$STEP_ID"
append_progress "$STEP_ID" "passed"

commit_on_pass="$(jq -r '.loop.commitOnPass // true' "$LOOP_CONFIG")"
if [[ "$commit_on_pass" == "true" ]] && git rev-parse --git-dir >/dev/null 2>&1; then
  if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    git add -A
    git commit -m "gen: complete step ${STEP_ID}" --no-verify 2>/dev/null || true
  fi
fi

if all_steps_pass; then
  echo "GEN_COMPLETE"
else
  gen_ok "Step ${STEP_ID} passed. Next: $(pick_next_step_id)"
fi
