#!/usr/bin/env bash
# Generator Ralph loop — fresh agent context each iteration
# Usage: gen-loop.sh [maxIterations]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_gen_deps
cd "$REPO_ROOT"

max="${1:-$(jq -r '.loop.maxIterations // 40' "$LOOP_CONFIG")}"
iter=0
last_failed_step=""
gate_fail_streak=0

gen_section "Generator loop (max=${max})" loop
print_gen_env

while [[ "$iter" -lt "$max" ]]; do
  if all_steps_pass; then
    echo "GEN_COMPLETE"
    exit 0
  fi

  iter=$((iter + 1))
  gen_section "Iteration ${iter}/${max}" iteration

  step_id="$(pick_next_step_id)"
  step_kind="$(get_step_field "$step_id" kind)"

  set +e
  "${GEN_SCRIPTS_DIR}/gen-once.sh"
  status=$?
  set -e

  if [[ "$status" -ne 0 ]]; then
    if [[ "$step_kind" == "gate" ]] && gate_recovery_enabled; then
      repair_count="$(get_gate_repair_count "$step_id")"
      max_repairs="$(gate_recovery_max_attempts)"
      if [[ "$repair_count" -lt "$max_repairs" ]]; then
        gen_step "Gate recovery: repair attempt $((repair_count + 1))/${max_repairs} for ${step_id}"
        set +e
        "${GEN_SCRIPTS_DIR}/run-gate-repair.sh" "$step_id"
        repair_status=$?
        set -e
        if [[ "$repair_status" -eq 0 ]]; then
          gen_step "Re-running gate after repair"
          set +e
          "${GEN_SCRIPTS_DIR}/gen-once.sh"
          status=$?
          set -e
        else
          gen_warn "Gate repair did not complete — continuing loop"
        fi
      else
        gen_warn "Gate repair attempts exhausted (${max_repairs}) for ${step_id}"
      fi
    fi
  fi

  if [[ "$status" -ne 0 ]]; then
    gen_warn "Iteration ${iter} did not pass; continuing with fresh context"
    if [[ "$step_kind" == "gate" || "$step_kind" == "scaffold" ]]; then
      if [[ "$step_id" == "$last_failed_step" ]]; then
        gate_fail_streak=$((gate_fail_streak + 1))
      else
        gate_fail_streak=1
        last_failed_step="$step_id"
      fi
      if [[ "$gate_fail_streak" -ge 3 ]]; then
        gen_err "${step_kind} step '${step_id}' failed ${gate_fail_streak} times in a row"
        gen_err "Fix generator scripts/validators or outputs manually, then re-run gen:once"
        exit 1
      fi
    else
      gate_fail_streak=0
      last_failed_step=""
    fi
  else
    gate_fail_streak=0
    last_failed_step=""
  fi

  if all_steps_pass; then
    echo "GEN_COMPLETE"
    exit 0
  fi
done

gen_err "Max iterations (${max}) reached"
remaining="$(jq '[.steps[] | select(.passes == false)] | length' "$STEPS_BACKLOG")"
gen_info "Remaining steps: ${remaining}"
exit 1
