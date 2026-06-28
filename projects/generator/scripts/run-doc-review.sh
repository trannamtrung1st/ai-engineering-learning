#!/usr/bin/env bash
# Optional AI doc review gate (read-only)
# Usage: run-doc-review.sh <stepId> [runId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps
require_agent

STEP_ID="${1:?step id required}"
RID="${2:-$(run_id)}"
ensure_runs_dir

cd "$REPO_ROOT"

prompt="$("${GEN_SCRIPTS_DIR}/build-prompt.sh" "$STEP_ID" doc-reviewer)"
outputs_list="$(step_outputs "$STEP_ID" | sed 's/^/- /')"

full_prompt="${prompt}

## Harness reminder

Review only the step outputs listed below. Do not run shell, npm, or write files.
End with REVIEW_PASS or REVIEW_FAIL on its own line.

## Step outputs to review

${outputs_list:-_(none)_}
"

outfile="${RUNS_DIR}/${RID}-review.txt"
model="$(get_model reviewer)"

gen_agent_begin "doc-reviewer (${model})"
set +e
agent_invoke_review "$model" "$full_prompt" "$outfile"
agent_status=$?
set -e
gen_agent_end "$agent_status"

if [[ "$agent_status" -ne 0 ]]; then
  append_guardrail "$STEP_ID" "Doc review agent failed — see ${RID}-review.txt"
  exit 1
fi

text="$(cat "$outfile")"
if echo "$text" | grep -q "REVIEW_FAIL"; then
  append_guardrail "$STEP_ID" "Doc review failed — see ${RID}-review.txt"
  exit 1
fi

if ! echo "$text" | grep -q "REVIEW_PASS"; then
  append_guardrail "$STEP_ID" "Doc review did not emit REVIEW_PASS"
  exit 1
fi

gen_ok "Doc review passed for ${STEP_ID}"
exit 0
