#!/usr/bin/env bash
# Build agent prompt for a generator step
# Usage: build-prompt.sh <stepId> [doc-writer|harness-planner|doc-reviewer]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

STEP_ID="${1:?step id required}"
MODE="${2:-$(step_agent "$STEP_ID")}"
[[ -z "$MODE" || "$MODE" == "null" ]] && MODE="doc-writer"

case "$MODE" in
  doc-writer|harness-planner|doc-reviewer) ;;
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

description="$(get_step_field "$STEP_ID" description)"
outputs_list="$(step_outputs "$STEP_ID" | sed 's/^/- /')"
context_list="$(step_context_docs "$STEP_ID" | sed 's/^/- /')"
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

echo "$prompt"
