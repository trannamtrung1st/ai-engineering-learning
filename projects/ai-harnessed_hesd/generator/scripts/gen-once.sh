#!/usr/bin/env bash
# Single generator iteration: agent/scaffold → verify → review → mark
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_gen_deps
cd "$REPO_ROOT"

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

  if [[ ! -f "$INITIAL_IDEA" ]]; then
    gen_err "Missing docs/initial-idea.md — create it before running generator"
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
  if [[ "$kind" == "gate" ]]; then
    cp "$verify_log" "${GEN_STATE_DIR}/last-gate-failure.txt"
    append_guardrail "$STEP_ID" "Gate verification failed — harness will attempt auto-repair on next loop iteration"
  else
    append_guardrail "$STEP_ID" "Verification failed for step ${STEP_ID} — re-run gen:once after fixes"
  fi
  append_progress "$STEP_ID" "verify_failed"
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
