#!/usr/bin/env bash
# Build agent prompt for a generator step
# Usage: build-prompt.sh <stepId> [doc-writer|harness-planner|harness-backlog-planner|doc-reviewer]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

STEP_ID="${1:?step id required}"
MODE="${2:-$(step_agent "$STEP_ID")}"
[[ -z "$MODE" || "$MODE" == "null" ]] && MODE="doc-writer"

case "$MODE" in
  doc-writer|harness-planner|harness-backlog-planner|doc-reviewer) ;;
  *)
    gen_err "unknown agent mode: $MODE"
    exit 1
    ;;
esac

template="${GEN_ROOT}/agents/${MODE}.prompt.md"
if [[ ! -f "$template" ]]; then
  gen_err "missing template: $template"
  exit 1
fi

discover_docs

description="$(get_step_field "$STEP_ID" description)"
outputs_list="$(step_outputs "$STEP_ID" | sed 's/^/- /')"
context_list="$(step_relevant_docs "$STEP_ID" | sed 's/^/- /')"
inventory_summary="$(docs_inventory_summary)"
seed_list="$(seed_docs_list | sed 's/^/- /')"
existing_list="$(existing_outputs_for_step "$STEP_ID" | sed 's/^/- /')"
[[ -z "$seed_list" ]] && seed_list="(none discovered)"
[[ -z "$existing_list" ]] && existing_list="(none — write from scratch)"

guardrails=""
if [[ -f "${GEN_STATE_DIR}/guardrails.md" ]]; then
  guardrails="$(tail -n 80 "${GEN_STATE_DIR}/guardrails.md")"
fi

prompt="$(cat "$template")"
prompt="${prompt//\{\{STEP_ID\}\}/$STEP_ID}"
prompt="${prompt//\{\{STEP_DESCRIPTION\}\}/$description}"
prompt="${prompt//\{\{STEP_OUTPUTS\}\}/$outputs_list}"
prompt="${prompt//\{\{STEP_CONTEXT_DOCS\}\}/$context_list}"
prompt="${prompt//\{\{GUARDRAILS\}\}/$guardrails}"
prompt="${prompt//\{\{REPO_ROOT\}\}/$REPO_ROOT}"
prompt="${prompt//\{\{INITIAL_IDEA\}\}/$INITIAL_IDEA}"
prompt="${prompt//\{\{DOCS_INVENTORY_SUMMARY\}\}/$inventory_summary}"
prompt="${prompt//\{\{SEED_DOCS\}\}/$seed_list}"
prompt="${prompt//\{\{EXISTING_OUTPUTS\}\}/$existing_list}"
prompt="${prompt//\{\{INPUT_MODE\}\}/$(gen_input_mode)}"

if [[ "$MODE" == "harness-backlog-planner" ]]; then
  backlog_plan_feedback="$(format_harness_backlog_plan_validation_feedback_block 2>/dev/null || true)"
  prompt="${prompt//\{\{BACKLOG_PLAN_VALIDATION_FEEDBACK_BLOCK\}\}/$backlog_plan_feedback}"
else
  prompt="${prompt//\{\{BACKLOG_PLAN_VALIDATION_FEEDBACK_BLOCK\}\}/}"
fi

if [[ "$STEP_ID" == "harness-backlog" && "$MODE" == "harness-planner" ]]; then
  plan_path="$(resolve_repo_path ai-harness/plans/whole-app-backlog.md)"
  plan_block=""
  if [[ -f "$plan_path" ]]; then
    line_count="$(wc -l < "$plan_path" | tr -d ' ')"
    max_lines=150
    if [[ "$line_count" -le "$max_lines" ]]; then
      plan_excerpt="$(cat "$plan_path")"
    else
      plan_excerpt="$(head -n "$max_lines" "$plan_path")"
      plan_excerpt="${plan_excerpt}

... (plan truncated — read full file at ai-harness/plans/whole-app-backlog.md)"
    fi
    plan_block="## Approved backlog plan

Read and implement \`ai-harness/plans/whole-app-backlog.md\` exactly — slice inventory, acceptance mapping, testingPlanRefs, and requiresPlan metadata must match the plan.

\`\`\`markdown
${plan_excerpt}
\`\`\`"
  else
    plan_block="## Backlog plan missing

The approved plan at \`ai-harness/plans/whole-app-backlog.md\` is missing. Complete step \`harness-backlog-plan\` first."
  fi
  prompt="${prompt}

${plan_block}"
fi

echo "$prompt"
