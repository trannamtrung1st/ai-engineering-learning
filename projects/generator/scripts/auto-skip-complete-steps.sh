#!/usr/bin/env bash
# Mark pending steps as passed when all outputs exist and pass validators.
# Usage: auto-skip-complete-steps.sh
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

discover_docs

if [[ "$(gen_input_mode)" == "greenfield" ]]; then
  gen_info "GEN_INPUT_MODE=greenfield — skipping auto-skip"
  exit 0
fi

skipped=0
while IFS= read -r step_id; do
  [[ -z "$step_id" ]] && continue

  if ! step_can_auto_skip "$step_id"; then
    continue
  fi

  gen_step "Auto-skip check: ${step_id}"
  set +e
  "${GEN_SCRIPTS_DIR}/verify-step.sh" "$step_id" >/dev/null 2>&1
  status=$?
  set -e

  if [[ "$status" -eq 0 ]]; then
    mark_step_passed "$step_id"
    append_progress "$step_id" "auto-skipped (outputs valid)"
    gen_ok "auto-skipped ${step_id}"
    skipped=$((skipped + 1))
  fi
done < <(jq -r '.steps[] | select(.passes == false) | .id' "$STEPS_BACKLOG")

if [[ "$skipped" -gt 0 ]]; then
  gen_ok "auto-skipped ${skipped} step(s)"
else
  gen_info "no steps eligible for auto-skip"
fi
