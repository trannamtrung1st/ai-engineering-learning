#!/usr/bin/env bash
# Generator step runners — agent invoke, verify/self-fix, combined harness backlog iteration.
# Sourced by gen-once.sh after common.sh.

HARNESS_BACKLOG_PLAN_STEP="harness-backlog-plan"
HARNESS_BACKLOG_JSON_STEP="harness-backlog"

step_passes() {
  local step_id="$1"
  [[ "$(get_step_field "$step_id" passes)" == "true" ]]
}

harness_backlog_combined_pending() {
  ! step_passes "$HARNESS_BACKLOG_PLAN_STEP" || ! step_passes "$HARNESS_BACKLOG_JSON_STEP"
}

should_run_harness_backlog_combined() {
  local step_id="$1"
  harness_backlog_combined_pending \
    && { [[ "$step_id" == "$HARNESS_BACKLOG_PLAN_STEP" ]] || [[ "$step_id" == "$HARNESS_BACKLOG_JSON_STEP" ]]; }
}

harness_backlog_plan_gate_max_retries() {
  if [[ -n "${GEN_HARNESS_BACKLOG_PLAN_MAX_RETRIES:-}" ]]; then
    echo "$GEN_HARNESS_BACKLOG_PLAN_MAX_RETRIES"
    return
  fi
  jq -r '.harnessBacklogPlanGate.maxRetries // 5' "$LOOP_CONFIG" 2>/dev/null || echo 5
}

gen_agent_outputs_reminder() {
  local step_id="$1"
  local out abs reminder=""
  while IFS= read -r out; do
    [[ -z "$out" ]] && continue
    abs="$(resolve_repo_path "$out")"
    reminder="${reminder}
Write exactly: \`${abs}\`"
  done < <(step_outputs "$step_id")
  echo "$reminder"
}

gen_agent_model_for_step() {
  local step_id="$1"
  local agent_mode model
  agent_mode="$(step_agent "$step_id")"
  model="$(get_model default)"
  [[ "$agent_mode" == "harness-planner" ]] && model="$(get_model harnessPlanner 2>/dev/null || get_model default)"
  [[ "$agent_mode" == "harness-backlog-planner" ]] && model="$(get_model harnessPlanner 2>/dev/null || get_model default)"
  echo "$model"
}

# Invoke agent for one generator step. Returns 0 on STEP_DONE; 1 on failure (guardrails recorded).
run_gen_agent_for_step() {
  local step_id="$1"
  local run_id="$2"
  local label_suffix="${3:-}"
  local agent_mode model prompt full_prompt outputs_reminder agent_out agent_status agent_text reason

  if [[ "${GEN_SKIP_AGENT:-}" == "1" ]]; then
    gen_warn "GEN_SKIP_AGENT=1 — skipping agent for ${step_id}"
    agent_out="${RUNS_DIR}/${run_id}-agent${label_suffix}.txt"
    echo "STEP_DONE ${step_id}" > "$agent_out"
    return 0
  fi

  require_agent
  agent_mode="$(step_agent "$step_id")"
  model="$(gen_agent_model_for_step "$step_id")"
  prompt="$("${GEN_SCRIPTS_DIR}/build-prompt.sh" "$step_id" "$agent_mode")"
  outputs_reminder="$(gen_agent_outputs_reminder "$step_id")"
  full_prompt="${prompt}

## Harness reminder

${outputs_reminder}

After writing all outputs, end with: STEP_DONE ${step_id}
"
  agent_out="${RUNS_DIR}/${run_id}-agent${label_suffix}.txt"
  gen_step "Running ${agent_mode} (${AGENT_BIN}, model=${model})"
  gen_agent_begin "${agent_mode} (${model})"
  set +e
  agent_invoke "$model" "$full_prompt" "$agent_out"
  agent_status=$?
  set -e
  gen_agent_end "$agent_status"

  if [[ "$agent_status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
    append_guardrail "$step_id" "Agent timed out — see $(basename "$agent_out")"
    append_progress "$step_id" "agent_timeout"
    return 1
  fi

  agent_text="$(cat "$agent_out")"
  if echo "$agent_text" | grep -q "STEP_BLOCKED"; then
    reason="$(echo "$agent_text" | grep "STEP_BLOCKED" | tail -1)"
    append_guardrail "$step_id" "$reason"
    append_progress "$step_id" "blocked"
    return 1
  fi

  if ! echo "$agent_text" | grep -q "STEP_DONE"; then
    append_guardrail "$step_id" "Agent did not emit STEP_DONE"
    append_progress "$step_id" "agent_failed"
    return 1
  fi

  return 0
}

# Verify step; optional self-fix pass. Returns 0 when verification passes.
run_gen_step_verify_with_self_fix() {
  local step_id="$1"
  local run_id="$2"
  local kind verify_log verify_status verify_feedback agent_mode fix_model fix_prompt fix_full_prompt
  local fix_outputs_reminder fix_out fix_agent_status fix_agent_text fix_reason

  kind="$(get_step_field "$step_id" kind)"
  gen_step "Running step verification: ${step_id}"
  verify_log="${RUNS_DIR}/${run_id}-verify-${step_id}.txt"
  set +e
  "${GEN_SCRIPTS_DIR}/verify-step.sh" "$step_id" 2>&1 | tee "$verify_log"
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
      append_guardrail "$step_id" "Verification failed for step ${step_id}. Running automatic self-fix pass before failing.

Verifier feedback:
${verify_feedback}

Full log: ${verify_log}"

      require_agent
      agent_mode="$(step_agent "$step_id")"
      fix_prompt="$("${GEN_SCRIPTS_DIR}/build-prompt.sh" "$step_id" "$agent_mode")"
      fix_model="$(gen_agent_model_for_step "$step_id")"
      fix_outputs_reminder="$(gen_agent_outputs_reminder "$step_id")"
      fix_full_prompt="${fix_prompt}

## Self-check fix pass

Your previous output failed verification. Apply targeted fixes now.

Verifier feedback:
${verify_feedback}

## Harness reminder

${fix_outputs_reminder}

After writing all outputs, end with: STEP_DONE ${step_id}
"
      fix_out="${RUNS_DIR}/${run_id}-self-fix-${step_id}.txt"
      gen_step "Running self-fix pass (${agent_mode}, model=${fix_model})"
      gen_agent_begin "self-fix ${agent_mode} (${fix_model})"
      set +e
      agent_invoke "$fix_model" "$fix_full_prompt" "$fix_out"
      fix_agent_status=$?
      set -e
      gen_agent_end "$fix_agent_status"

      if [[ "$fix_agent_status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
        append_guardrail "$step_id" "Self-fix pass timed out — see $(basename "$fix_out")"
        append_progress "$step_id" "verify_self_fix_timeout"
        return 1
      fi

      fix_agent_text="$(cat "$fix_out")"
      if echo "$fix_agent_text" | grep -q "STEP_BLOCKED"; then
        fix_reason="$(echo "$fix_agent_text" | grep "STEP_BLOCKED" | tail -1)"
        append_guardrail "$step_id" "Self-fix pass blocked: ${fix_reason}"
        append_progress "$step_id" "verify_self_fix_blocked"
        return 1
      fi

      if ! echo "$fix_agent_text" | grep -q "STEP_DONE"; then
        append_guardrail "$step_id" "Self-fix pass did not emit STEP_DONE"
        append_progress "$step_id" "verify_self_fix_failed"
        return 1
      fi

      gen_step "Re-running step verification after self-fix: ${step_id}"
      verify_log="${RUNS_DIR}/${run_id}-verify-self-fix-${step_id}.txt"
      set +e
      "${GEN_SCRIPTS_DIR}/verify-step.sh" "$step_id" 2>&1 | tee "$verify_log"
      verify_status=${PIPESTATUS[0]}
      set -e
    fi

    if [[ "$verify_status" -eq 0 ]]; then
      append_progress "$step_id" "verify_self_fix_passed"
      gen_ok "Verification passed after self-fix: ${step_id}"
      return 0
    fi

    if [[ "$kind" == "gate" ]]; then
      cp "$verify_log" "${GEN_STATE_DIR}/last-gate-failure.txt"
      append_guardrail "$step_id" "Gate verification failed — harness will attempt auto-repair on next loop iteration.

Verifier feedback:
${verify_feedback}

Full log: ${verify_log}"
    else
      append_guardrail "$step_id" "Verification failed for step ${step_id}.

Use this verifier feedback to fix outputs in the next attempt:
${verify_feedback}

Full log: ${verify_log}"
    fi
    append_progress "$step_id" "verify_failed"
    return 1
  fi

  return 0
}

# Inner retry loop for backlog plan markdown (same gen-once iteration as JSON step).
run_harness_backlog_plan_gate() {
  local run_id="$1"
  local max_retries attempt plan_path plan_validate_output plan_validate_status suffix

  plan_path="$(resolve_repo_path ai-harness/plans/whole-app-backlog.md)"
  mkdir -p "$(dirname "$plan_path")"
  max_retries="$(harness_backlog_plan_gate_max_retries)"
  attempt=0

  while true; do
    attempt=$((attempt + 1))
    if [[ "$attempt" -gt "$max_retries" ]]; then
      append_guardrail "$HARNESS_BACKLOG_PLAN_STEP" \
        "Backlog plan gate failed after ${max_retries} attempt(s) — run: validate-harness-backlog-plan.sh"
      append_progress "$HARNESS_BACKLOG_PLAN_STEP" "plan_validation_failed"
      gen_err "Harness backlog plan gate exhausted ${max_retries} retries"
      return 1
    fi

    if [[ "$attempt" -gt 1 ]]; then
      gen_warn "Harness backlog plan retry ${attempt}/${max_retries} (same generator iteration)"
    fi

    suffix=""
    [[ "$attempt" -gt 1 ]] && suffix="-r${attempt}"

    if ! run_gen_agent_for_step "$HARNESS_BACKLOG_PLAN_STEP" "$run_id" "$suffix"; then
      return 1
    fi

    set +e
    plan_validate_output="$("${GEN_SCRIPTS_DIR}/validate-harness-backlog-plan.sh" --quiet 2>&1)"
    plan_validate_status=$?
    set -e
    if [[ "$plan_validate_status" -ne 0 ]]; then
      write_harness_backlog_plan_validation_feedback "$plan_validate_output"
      gen_warn "Harness backlog plan validation failed (attempt ${attempt}/${max_retries})"
      continue
    fi

    clear_harness_backlog_plan_validation_feedback
    gen_ok "Harness backlog plan approved (attempt ${attempt})"
    return 0
  done
}

# Plan gate (inner retries) + verify + JSON agent in one gen-loop iteration — separate agent sessions.
run_harness_backlog_combined_iteration() {
  local run_id="$1"
  local -a completed_steps=()

  gen_step "Combined harness backlog iteration: ${HARNESS_BACKLOG_PLAN_STEP} → ${HARNESS_BACKLOG_JSON_STEP} (separate agent sessions)"

  if ! step_passes "$HARNESS_BACKLOG_PLAN_STEP"; then
    if ! run_harness_backlog_plan_gate "$run_id"; then
      return 1
    fi
    if ! run_gen_step_verify_with_self_fix "$HARNESS_BACKLOG_PLAN_STEP" "$run_id"; then
      return 1
    fi
    mark_step_passed "$HARNESS_BACKLOG_PLAN_STEP"
    append_progress "$HARNESS_BACKLOG_PLAN_STEP" "passed"
    completed_steps+=("$HARNESS_BACKLOG_PLAN_STEP")
  else
    gen_ok "Harness backlog plan step already passed — skipping planner"
    set +e
    "${GEN_SCRIPTS_DIR}/validate-harness-backlog-plan.sh" --quiet
    plan_validate_status=$?
    set -e
    if [[ "$plan_validate_status" -ne 0 ]]; then
      gen_err "harness-backlog plan validation failed — re-run harness-backlog-plan or fix ai-harness/plans/whole-app-backlog.md"
      return 1
    fi
  fi

  if ! step_passes "$HARNESS_BACKLOG_JSON_STEP"; then
    if ! run_gen_agent_for_step "$HARNESS_BACKLOG_JSON_STEP" "$run_id"; then
      return 1
    fi
    if ! run_gen_step_verify_with_self_fix "$HARNESS_BACKLOG_JSON_STEP" "$run_id"; then
      return 1
    fi
    mark_step_passed "$HARNESS_BACKLOG_JSON_STEP"
    append_progress "$HARNESS_BACKLOG_JSON_STEP" "passed"
    completed_steps+=("$HARNESS_BACKLOG_JSON_STEP")
  fi

  local review_required review_step
  review_required="$(jq -r '.aiReview.required // false' "$LOOP_CONFIG")"
  if [[ "$review_required" == "true" && "${GEN_SKIP_REVIEW:-}" != "1" ]]; then
    for review_step in "${completed_steps[@]}"; do
      gen_step "Running doc review: ${review_step}"
      set +e
      "${GEN_SCRIPTS_DIR}/run-doc-review.sh" "$review_step" "$run_id"
      review_status=$?
      set -e
      if [[ "$review_status" -ne 0 ]]; then
        append_progress "$review_step" "review_failed"
        return 1
      fi
    done
  fi

  return 0
}
