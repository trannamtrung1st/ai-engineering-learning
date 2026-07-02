#!/usr/bin/env bash
# Run doc-writer repair after a gate verification failure
# Usage: run-gate-repair.sh <gateStepId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

GATE_STEP_ID="${1:?gate step id required}"
FAILURE_LOG="${GEN_STATE_DIR}/last-gate-failure.txt"
REPAIR_STATE="${GEN_STATE_DIR}/gate-repair-counts.json"

require_gen_deps
cd "$REPO_ROOT"

if [[ ! -f "$FAILURE_LOG" ]] || [[ ! -s "$FAILURE_LOG" ]]; then
  gen_warn "No gate failure log at ${FAILURE_LOG}"
  exit 1
fi

if [[ "${GEN_SKIP_AGENT:-}" == "1" ]]; then
  gen_warn "GEN_SKIP_AGENT=1 — skipping gate repair agent"
  exit 1
fi

repair_files=()
while IFS= read -r abs; do
  [[ -z "$abs" ]] && continue
  rel="${abs#"$REPO_ROOT"/}"
  repair_files+=("$rel")
done < <(grep -E '^ERROR: .+\.md:' "$FAILURE_LOG" 2>/dev/null \
  | sed -E 's/^ERROR: ([^:]+):.*/\1/' \
  | sort -u || true)

if [[ ${#repair_files[@]} -eq 0 ]]; then
  gen_warn "Gate failure log has no repairable doc paths"
  exit 1
fi

repair_list=""
for f in "${repair_files[@]}"; do
  repair_list="${repair_list}- ${f}
"
done

failures="$(grep -E '^ERROR:|^✗' "$FAILURE_LOG" 2>/dev/null || cat "$FAILURE_LOG")"
description="$(get_step_field "$GATE_STEP_ID" description)"
guardrails=""
if [[ -f "${GEN_STATE_DIR}/guardrails.md" ]]; then
  guardrails="$(tail -n 40 "${GEN_STATE_DIR}/guardrails.md")"
fi

template="${GEN_ROOT}/agents/gate-repair.prompt.md"
prompt="$(cat "$template")"
prompt="${prompt//\{\{GATE_STEP_ID\}\}/$GATE_STEP_ID}"
prompt="${prompt//\{\{GATE_STEP_DESCRIPTION\}\}/$description}"
prompt="${prompt//\{\{GATE_FAILURES\}\}/$failures}"
prompt="${prompt//\{\{REPAIR_FILES\}\}/$repair_list}"
prompt="${prompt//\{\{GUARDRAILS\}\}/$guardrails}"

abs_paths=""
for f in "${repair_files[@]}"; do
  abs_paths="${abs_paths}
Edit exactly: \`$(resolve_repo_path "$f")\`"
done

full_prompt="${prompt}

## Harness reminder
${abs_paths}

After fixing all validator errors, end with: GATE_REPAIR_DONE ${GATE_STEP_ID}
"

assert_can_write_outputs
require_agent

RID="$(run_id)"
ensure_runs_dir
agent_out="${RUNS_DIR}/${RID}-gate-repair.txt"
model="$(get_model default)"

gen_step "Running gate repair agent (${AGENT_BIN}, model=${model})"
gen_agent_begin "gate-repair (${model})"
set +e
agent_invoke "$model" "$full_prompt" "$agent_out"
agent_status=$?
set -e
gen_agent_end "$agent_status"

if [[ "$agent_status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
  append_guardrail "$GATE_STEP_ID" "Gate repair agent timed out — see ${RID}-gate-repair.txt"
  exit 1
fi

agent_text="$(cat "$agent_out")"
if echo "$agent_text" | grep -q "GATE_REPAIR_BLOCKED"; then
  reason="$(echo "$agent_text" | grep "GATE_REPAIR_BLOCKED" | tail -1)"
  append_guardrail "$GATE_STEP_ID" "$reason"
  exit 1
fi

if ! echo "$agent_text" | grep -q "GATE_REPAIR_DONE"; then
  append_guardrail "$GATE_STEP_ID" "Gate repair agent did not emit GATE_REPAIR_DONE"
  exit 1
fi

increment_gate_repair_count "$GATE_STEP_ID"
append_progress "$GATE_STEP_ID" "gate_repair_done"
gen_ok "Gate repair completed for ${GATE_STEP_ID}"
exit 0
