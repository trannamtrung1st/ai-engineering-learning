#!/usr/bin/env bash
# Single ManualsGen iteration — generate one user manual artifact
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/doc-fingerprint.sh
source "$(dirname "$0")/lib/doc-fingerprint.sh"

require_harness_deps
cd "$REPO_ROOT"

if [[ ! -f "$MANUALS_BACKLOG" ]]; then
  aih_err "Missing ${MANUALS_BACKLOG} — run harness planner (harness-context-maps step)"
  exit 1
fi

if all_manuals_current; then
  echo "MANUALSGEN_COMPLETE"
  exit 0
fi

if implementation_gate_blocks_manualsgen; then
  aih_err "Implementation gate active — all Ralph slices must pass before ManualsGen (or set implementationGate.mode to optional)"
  exit 1
fi

MANUAL_ITEM_ID="${1:-$(pick_next_manualsgen_item)}"
if [[ -z "$MANUAL_ITEM_ID" ]]; then
  if all_manuals_current; then
    echo "MANUALSGEN_COMPLETE"
    exit 0
  fi
  aih_err "No eligible manual item (runbook may be waiting for flow items)"
  exit 1
fi

aih_step "ManualsGen iteration: item=${MANUAL_ITEM_ID}"

RID="$(run_id)"
ensure_runs_dir
artifact_dir="$(dirname "$(manual_artifact_abs "$MANUAL_ITEM_ID")")"
mkdir -p "$artifact_dir" "${USER_MANUALS_DIR}/modules" "${USER_MANUALS_DIR}/flows"

set +e
./ai-harness/scripts/check-manuals-drift.sh "$MANUAL_ITEM_ID" 2>&1
drift_status=$?
set -e
if [[ "$drift_status" -ne 0 ]]; then
  aih_info "Doc drift reset applied for ${MANUAL_ITEM_ID}"
fi

DOC_FP="$(compute_manual_item_doc_fingerprint "$MANUAL_ITEM_ID")"
ARTIFACT="$(manual_artifact_abs "$MANUAL_ITEM_ID")"

if [[ "${AIH_SKIP_MANUALSGEN_AGENT:-}" == "1" ]]; then
  aih_warn "AIH_SKIP_MANUALSGEN_AGENT=1 — skipping manualsgen agent"
  agent_out="${RUNS_DIR}/${RID}-manualsgen.txt"
  echo "MANUALSGEN_DONE ${MANUAL_ITEM_ID}" > "$agent_out"
else
  require_agent
  prompt="$(./ai-harness/scripts/build-prompt.sh manualsgen "$MANUAL_ITEM_ID")"
  model="$(get_model manualsgen)"
  agent_out="${RUNS_DIR}/${RID}-manualsgen.txt"

  review_reminder=""
  if [[ -f "$ARTIFACT" && "$(manualsgen_regeneration_mode)" == "incremental" ]]; then
    review_reminder="
Review and update the existing artifact at \`$(manual_artifact_path "$MANUAL_ITEM_ID")\` — change only what docs require."
    aih_step "Incremental review: existing artifact for ${MANUAL_ITEM_ID}"
  fi

  full_prompt="${prompt}

## Harness reminder

Write the user manual markdown artifact to exactly: \`${ARTIFACT}\`
Set docFingerprint in frontmatter to exactly: \`${DOC_FP}\`
Set manualItemId in frontmatter to exactly: \`${MANUAL_ITEM_ID}\`
Update \`docs/user-manuals/README.md\` with a link to this artifact.
Do not edit any other files.${review_reminder}

After writing the artifact and README link, end with: MANUALSGEN_DONE ${MANUAL_ITEM_ID}
"

  aih_step "Running manualsgen agent (${AGENT_BIN}, model=${model})"
  aih_agent_begin "manualsgen (${model})"
  set +e
  agent_invoke_manualsgen "$model" "$full_prompt" "$agent_out"
  agent_status=$?
  set -e
  aih_agent_end "${agent_status}"
fi

if [[ "${agent_status:-0}" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
  timeout_ms="$(get_agent_timeout_ms "$MANUALSGEN_CONFIG")"
  append_guardrail "$MANUAL_ITEM_ID" "ManualsGen agent timed out after ${timeout_ms}ms — see ${RID}-manualsgen.txt"
  append_progress "$MANUAL_ITEM_ID" "manualsgen_timeout"
  aih_err "ManualsGen agent timed out. See guardrails.md"
  exit 1
fi

agent_text="$(cat "$agent_out")"
if echo "$agent_text" | grep -q "MANUALSGEN_BLOCKED"; then
  reason="$(echo "$agent_text" | grep "MANUALSGEN_BLOCKED" | tail -1)"
  append_guardrail "$MANUAL_ITEM_ID" "$reason"
  append_progress "$MANUAL_ITEM_ID" "manualsgen_blocked"
  aih_err "ManualsGen blocked. See guardrails.md"
  exit 1
fi

if ! echo "$agent_text" | grep -q "MANUALSGEN_DONE"; then
  append_guardrail "$MANUAL_ITEM_ID" "ManualsGen agent did not emit MANUALSGEN_DONE"
  append_progress "$MANUAL_ITEM_ID" "manualsgen_failed"
  aih_err "ManualsGen agent did not signal MANUALSGEN_DONE"
  exit 1
fi

aih_step "Validating user manual"
set +e
validate_out="$(./ai-harness/scripts/validate-user-manuals.sh "$MANUAL_ITEM_ID" 2>&1)"
validate_status=$?
set -e
echo "$validate_out"

if [[ "$validate_status" -ne 0 ]]; then
  append_guardrail "$MANUAL_ITEM_ID" "Manual validation failed — see ${RID}-manualsgen.txt"
  append_progress "$MANUAL_ITEM_ID" "manualsgen_validation_failed"
  exit 1
fi

mark_manual_current "$MANUAL_ITEM_ID" "$DOC_FP"
append_progress "$MANUAL_ITEM_ID" "manualsgen_passed"

commit_on_pass="$(jq -r '.loop.commitOnPass // true' "$MANUALSGEN_CONFIG")"
if [[ "$commit_on_pass" == "true" ]]; then
  "$(dirname "$0")/git-commit-manualsgen.sh" "$MANUAL_ITEM_ID"
fi

if all_manuals_current; then
  echo "MANUALSGEN_COMPLETE"
else
  aih_ok "User manual generated for ${MANUAL_ITEM_ID}. Next: $(pick_next_manualsgen_item)"
fi
