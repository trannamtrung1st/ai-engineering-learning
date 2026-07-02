#!/usr/bin/env bash
# Single generator iteration: agent/scaffold → verify → review → mark
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

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
agent_status=0

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

  if [[ "${GEN_SKIP_AGENT:-}" == "1" ]]; then
    gen_warn "GEN_SKIP_AGENT=1 — skipping agent"
    agent_out="${RUNS_DIR}/${RID}-agent.txt"
    echo "STEP_DONE ${STEP_ID}" > "$agent_out"
  else
    require_agent
    agent_mode="$(step_agent "$STEP_ID")"
    prompt="$("${GEN_SCRIPTS_DIR}/build-prompt.sh" "$STEP_ID" "$agent_mode")"
    model="$(get_model default)"
    [[ "$agent_mode" == "harness-planner" ]] && model="$(get_model harnessPlanner 2>/dev/null || get_model default)"

    outputs_reminder=""
    while IFS= read -r out; do
      [[ -z "$out" ]] && continue
      abs="$(resolve_repo_path "$out")"
      outputs_reminder="${outputs_reminder}
Write exactly: \`${abs}\`"
    done < <(step_outputs "$STEP_ID")

    full_prompt="${prompt}

## Harness reminder

${outputs_reminder}

After writing all outputs, end with: STEP_DONE ${STEP_ID}
"

    agent_out="${RUNS_DIR}/${RID}-agent.txt"
    gen_step "Running ${agent_mode} (${AGENT_BIN}, model=${model})"
    gen_agent_begin "${agent_mode} (${model})"
    set +e
    agent_invoke "$model" "$full_prompt" "$agent_out"
    agent_status=$?
    set -e
    gen_agent_end "$agent_status"
  fi

  if [[ "${agent_status:-0}" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
    append_guardrail "$STEP_ID" "Agent timed out — see ${RID}-agent.txt"
    append_progress "$STEP_ID" "agent_timeout"
    exit 1
  fi

  agent_text="$(cat "$agent_out")"
  if echo "$agent_text" | grep -q "STEP_BLOCKED"; then
    reason="$(echo "$agent_text" | grep "STEP_BLOCKED" | tail -1)"
    append_guardrail "$STEP_ID" "$reason"
    append_progress "$STEP_ID" "blocked"
    exit 1
  fi

  if ! echo "$agent_text" | grep -q "STEP_DONE"; then
    append_guardrail "$STEP_ID" "Agent did not emit STEP_DONE"
    append_progress "$STEP_ID" "agent_failed"
    exit 1
  fi
fi

# --- Verification ---
gen_step "Running step verification"
verify_log="${RUNS_DIR}/${RID}-verify.txt"
set +e
"${GEN_SCRIPTS_DIR}/verify-step.sh" "$STEP_ID" 2>&1 | tee "$verify_log"
verify_status=${PIPESTATUS[0]}
set -e

if [[ "$verify_status" -ne 0 ]]; then
  verify_feedback="$(
    awk '
      /ERROR:/ || /WARN:/ || /forbidden placeholder/ || /missing required/ || /missing output:/ || /verification failed/ {
        print
      }
    ' "$verify_log" | tail -n 40
  )"
  if [[ -z "$verify_feedback" ]]; then
    verify_feedback="$(tail -n 40 "$verify_log")"
  fi

  if [[ "$kind" == "agent" && "${GEN_SKIP_AGENT:-}" != "1" && "${GEN_VERIFY_SELF_FIX:-1}" == "1" ]]; then
    append_guardrail "$STEP_ID" "Verification failed for step ${STEP_ID}. Running automatic self-fix pass before failing.

Verifier feedback:
${verify_feedback}

Full log: ${verify_log}"

    require_agent
    agent_mode="$(step_agent "$STEP_ID")"
    fix_prompt="$("${GEN_SCRIPTS_DIR}/build-prompt.sh" "$STEP_ID" "$agent_mode")"
    fix_model="$(get_model default)"
    [[ "$agent_mode" == "harness-planner" ]] && fix_model="$(get_model harnessPlanner 2>/dev/null || get_model default)"

    fix_outputs_reminder=""
    while IFS= read -r out; do
      [[ -z "$out" ]] && continue
      abs="$(resolve_repo_path "$out")"
      fix_outputs_reminder="${fix_outputs_reminder}
Write exactly: \`${abs}\`"
    done < <(step_outputs "$STEP_ID")

    fix_full_prompt="${fix_prompt}

## Self-check fix pass

Your previous output failed verification. Apply targeted fixes now.

Verifier feedback:
${verify_feedback}

## Harness reminder

${fix_outputs_reminder}

After writing all outputs, end with: STEP_DONE ${STEP_ID}
"

    fix_out="${RUNS_DIR}/${RID}-self-fix-agent.txt"
    gen_step "Running self-fix pass (${agent_mode}, model=${fix_model})"
    gen_agent_begin "self-fix ${agent_mode} (${fix_model})"
    set +e
    agent_invoke "$fix_model" "$fix_full_prompt" "$fix_out"
    fix_agent_status=$?
    set -e
    gen_agent_end "$fix_agent_status"

    if [[ "$fix_agent_status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
      append_guardrail "$STEP_ID" "Self-fix pass timed out — see ${RID}-self-fix-agent.txt"
      append_progress "$STEP_ID" "verify_self_fix_timeout"
      exit 1
    fi

    fix_agent_text="$(cat "$fix_out")"
    if echo "$fix_agent_text" | grep -q "STEP_BLOCKED"; then
      fix_reason="$(echo "$fix_agent_text" | grep "STEP_BLOCKED" | tail -1)"
      append_guardrail "$STEP_ID" "Self-fix pass blocked: ${fix_reason}"
      append_progress "$STEP_ID" "verify_self_fix_blocked"
      exit 1
    fi

    if ! echo "$fix_agent_text" | grep -q "STEP_DONE"; then
      append_guardrail "$STEP_ID" "Self-fix pass did not emit STEP_DONE"
      append_progress "$STEP_ID" "verify_self_fix_failed"
      exit 1
    fi

    gen_step "Re-running step verification after self-fix"
    verify_log="${RUNS_DIR}/${RID}-verify-self-fix.txt"
    set +e
    "${GEN_SCRIPTS_DIR}/verify-step.sh" "$STEP_ID" 2>&1 | tee "$verify_log"
    verify_status=${PIPESTATUS[0]}
    set -e
  fi

  if [[ "$verify_status" -eq 0 ]]; then
    append_progress "$STEP_ID" "verify_self_fix_passed"
    gen_ok "Verification passed after self-fix"
  else
  if [[ "$kind" == "gate" ]]; then
    cp "$verify_log" "${GEN_STATE_DIR}/last-gate-failure.txt"
    append_guardrail "$STEP_ID" "Gate verification failed — harness will attempt auto-repair on next loop iteration.

Verifier feedback:
${verify_feedback}

Full log: ${verify_log}"
  else
    append_guardrail "$STEP_ID" "Verification failed for step ${STEP_ID}.

Use this verifier feedback to fix outputs in the next attempt:
${verify_feedback}

Full log: ${verify_log}"
  fi
  append_progress "$STEP_ID" "verify_failed"
  exit 1
  fi
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
