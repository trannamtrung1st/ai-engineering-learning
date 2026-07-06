#!/usr/bin/env bash
# Validate generator internals before running loops.
# Usage: self-check.sh
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

fail=0

check_file_exists() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    gen_err "missing required file: ${path}"
    fail=1
  fi
}

check_json() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    gen_err "missing json: ${path}"
    fail=1
    return
  fi
  if ! jq empty "$path" >/dev/null 2>&1; then
    gen_err "invalid json: ${path}"
    fail=1
  fi
}

gen_step "Self-check: required generator files"
check_file_exists "$STEPS_BACKLOG"
check_file_exists "$LOOP_CONFIG"
check_file_exists "$MODELS_CONFIG"
check_file_exists "$DOC_OUTLINES"
check_file_exists "${GEN_ROOT}/schemas/step-backlog.schema.json"
check_file_exists "${GEN_ROOT}/schemas/docs-inventory.schema.json"
check_file_exists "${GEN_ROOT}/agents/doc-writer.prompt.md"
check_file_exists "${GEN_ROOT}/agents/harness-planner.prompt.md"
check_file_exists "${GEN_ROOT}/agents/gate-repair.prompt.md"

gen_step "Self-check: JSON parse"
check_json "$STEPS_BACKLOG"
check_json "$LOOP_CONFIG"
check_json "$MODELS_CONFIG"
check_json "$DOC_OUTLINES"
check_json "${GEN_ROOT}/config/product-meta.schema.json"
check_json "${GEN_ROOT}/schemas/step-backlog.schema.json"
check_json "${GEN_ROOT}/schemas/docs-inventory.schema.json"
check_json "${TEMPLATES_DIR}/ai-harness/test-cases/common/ui-ux-suite.json"
check_json "${TEMPLATES_DIR}/ai-harness/schemas/ui-ux-suite.schema.json"
check_json "${TEMPLATES_DIR}/ai-harness/workflows/ralph-loop.json"
check_file_exists "${TEMPLATES_DIR}/ai-harness/scripts/run-playwright-check.sh"
check_file_exists "${TEMPLATES_DIR}/ai-harness/scripts/lib/integration-failure-triage.js"
check_file_exists "${TEMPLATES_DIR}/ai-harness/scripts/lib/integration-failure-triage.test.js"
check_file_exists "${TEMPLATES_DIR}/ai-harness/scripts/verify-integration.sh"
check_file_exists "${TEMPLATES_DIR}/ai-harness/docs/integration-debt-register.md"
check_file_exists "${TEMPLATES_DIR}/ai-harness/docs/integration-checklist.md"
check_json "${TEMPLATES_DIR}/ai-harness/config/integration-checks.json"
check_json "${TEMPLATES_DIR}/ai-harness/schemas/integration-checks.schema.json"

gen_step "Self-check: integration verify script"
if [[ ! -x "${TEMPLATES_DIR}/ai-harness/scripts/verify-integration.sh" ]]; then
  gen_err "verify-integration.sh must be executable"
  fail=1
fi

gen_step "Self-check: implementer prompt integration docs"
if ! grep -q 'integration-debt-register.md' "${TEMPLATES_DIR}/ai-harness/agents/implementer.prompt.md" 2>/dev/null; then
  gen_err "implementer.prompt.md must reference integration-debt-register.md"
  fail=1
fi
if grep -q 'mvp-integration' "${TEMPLATES_DIR}/ai-harness/agents/implementer.prompt.md" 2>/dev/null; then
  gen_err "implementer.prompt.md must not reference mvp-integration (use generic integration-debt docs)"
  fail=1
fi

gen_step "Self-check: repo bootstrap integration script"
if ! grep -q 'aih:verify:integration' "${GEN_SCRIPTS_DIR}/emit-repo-bootstrap.sh" 2>/dev/null; then
  gen_err "emit-repo-bootstrap.sh missing aih:verify:integration"
  fail=1
fi

gen_step "Self-check: harness integration triage policy"
if [[ -f "${TEMPLATES_DIR}/ai-harness/workflows/ralph-loop.json" ]]; then
  if [[ "$(jq -r '.computationalChecks.integrationFailurePolicy.investigateOnFailure // false' "${TEMPLATES_DIR}/ai-harness/workflows/ralph-loop.json")" != "true" ]]; then
    gen_err "ralph-loop.json missing integrationFailurePolicy.investigateOnFailure"
    fail=1
  fi
fi

gen_step "Self-check: integration failure triage unit tests"
if ! node --test "${TEMPLATES_DIR}/ai-harness/scripts/lib/integration-failure-triage.test.js" >/dev/null 2>&1; then
  gen_err "integration-failure-triage.test.js failed"
  fail=1
fi

gen_step "Self-check: integration gate and browser hardening"
if [[ -f "${TEMPLATES_DIR}/ai-harness/workflows/ralph-loop.json" ]]; then
  if [[ "$(jq -r '.integrationGate.enabled // false' "${TEMPLATES_DIR}/ai-harness/workflows/ralph-loop.json")" != "true" ]]; then
    gen_err "ralph-loop.json missing integrationGate.enabled"
    fail=1
  fi
  if [[ "$(jq -r '.browserTest.acceptanceSliceTimeoutMinutes // empty' "${TEMPLATES_DIR}/ai-harness/workflows/ralph-loop.json")" == "" ]]; then
    gen_err "ralph-loop.json missing browserTest.acceptanceSliceTimeoutMinutes"
    fail=1
  fi
fi
if ! grep -q 'test-results/.last-run.json' "${TEMPLATES_DIR}/ai-harness/docs/integration-checklist.md" 2>/dev/null; then
  gen_err "integration-checklist.md must document test-results/.last-run.json hygiene"
  fail=1
fi
if ! jq -e '.properties.jwtEnvVars' "${TEMPLATES_DIR}/ai-harness/schemas/integration-checks.schema.json" >/dev/null 2>&1; then
  gen_err "integration-checks.schema.json missing jwtEnvVars"
  fail=1
fi
if ! jq -e '.properties.bootstrapAdminEnvVars' "${TEMPLATES_DIR}/ai-harness/schemas/integration-checks.schema.json" >/dev/null 2>&1; then
  gen_err "integration-checks.schema.json missing bootstrapAdminEnvVars"
  fail=1
fi
if ! grep -q 'bootstrap-admin' "${TEMPLATES_DIR}/ai-harness/scripts/verify-integration.sh" 2>/dev/null; then
  gen_err "verify-integration.sh missing bootstrap-admin check"
  fail=1
fi
if ! grep -q 'jwt-env' "${TEMPLATES_DIR}/ai-harness/scripts/verify-integration.sh" 2>/dev/null; then
  gen_err "verify-integration.sh missing jwt-env check"
  fail=1
fi
if [[ ! -f "${TEMPLATES_DIR}/tests/playwright-ui/.gitignore" ]]; then
  gen_err "missing templates/tests/playwright-ui/.gitignore"
  fail=1
fi
if ! grep -q 'playwright-ui/test-results' "${GEN_SCRIPTS_DIR}/emit-repo-bootstrap.sh" 2>/dev/null; then
  gen_err "emit-repo-bootstrap.sh must gitignore playwright-ui test-results"
  fail=1
fi

gen_step "Self-check: playwright spec resolution unit tests"
if ! node --test "${TEMPLATES_DIR}/ai-harness/scripts/lib/playwright-scope-sync.test.js" >/dev/null 2>&1; then
  gen_err "playwright-scope-sync.test.js failed"
  fail=1
fi

gen_step "Self-check: plan gate fixture tests"
if ! bash "${TEMPLATES_DIR}/ai-harness/scripts/lib/plan-gate-fixtures.test.sh" >/dev/null 2>&1; then
  gen_err "plan-gate-fixtures.test.sh failed — run: bash templates/ai-harness/scripts/lib/plan-gate-fixtures.test.sh"
  fail=1
fi

gen_step "Self-check: harness backlog plan step"
check_file_exists "${GEN_ROOT}/agents/harness-backlog-planner.prompt.md"
check_file_exists "${GEN_SCRIPTS_DIR}/validate-harness-backlog-plan.sh"
if ! jq -e '.steps[] | select(.id == "harness-backlog-plan")' "$STEPS_BACKLOG" >/dev/null 2>&1; then
  gen_err "steps-backlog.json missing harness-backlog-plan step"
  fail=1
fi
plan_prio="$(jq -r '.steps[] | select(.id == "harness-backlog-plan") | .priority' "$STEPS_BACKLOG")"
backlog_prio="$(jq -r '.steps[] | select(.id == "harness-backlog") | .priority' "$STEPS_BACKLOG")"
if [[ "$plan_prio" -ge "$backlog_prio" ]]; then
  gen_err "harness-backlog-plan priority must be less than harness-backlog"
  fail=1
fi

gen_step "Self-check: slice plan gate templates"
check_file_exists "${TEMPLATES_DIR}/ai-harness/agents/slice-planner.prompt.md"
check_file_exists "${TEMPLATES_DIR}/ai-harness/scripts/validate-slice-plan.sh"
check_file_exists "${TEMPLATES_DIR}/ai-harness/scripts/check-plan-drift.sh"
check_file_exists "${TEMPLATES_DIR}/ai-harness/config/plan-index.json"
check_json "${TEMPLATES_DIR}/ai-harness/schemas/slice-plan.schema.json"
if [[ "$(jq -r '.slicePlanGate.mode // empty' "${TEMPLATES_DIR}/ai-harness/workflows/ralph-loop.json")" != "required" ]]; then
  gen_err "ralph-loop.json missing slicePlanGate.mode required"
  fail=1
fi
if [[ "$(jq -r '.slicePlanGate.requireExplicitRequiresPlan // false' "${TEMPLATES_DIR}/ai-harness/workflows/ralph-loop.json")" != "true" ]]; then
  gen_err "ralph-loop.json missing slicePlanGate.requireExplicitRequiresPlan"
  fail=1
fi
if ! grep -q 'Approved implementation plan' "${TEMPLATES_DIR}/ai-harness/agents/implementer.prompt.md" 2>/dev/null; then
  gen_err "implementer.prompt.md must reference approved implementation plan"
  fail=1
fi
if ! grep -q 'PRIOR_GATE_FAILURES_BLOCK' "${TEMPLATES_DIR}/ai-harness/agents/implementer.prompt.md" 2>/dev/null; then
  gen_err "implementer.prompt.md must include PRIOR_GATE_FAILURES_BLOCK placeholder"
  fail=1
fi
if ! grep -q 'PLAN_VALIDATION_FEEDBACK_BLOCK' "${TEMPLATES_DIR}/ai-harness/agents/slice-planner.prompt.md" 2>/dev/null; then
  gen_err "slice-planner.prompt.md must include PLAN_VALIDATION_FEEDBACK_BLOCK placeholder"
  fail=1
fi

gen_step "Self-check: backlog sanity"
if [[ -f "$STEPS_BACKLOG" ]]; then
  pending="$(jq '[.steps[]?] | length' "$STEPS_BACKLOG" 2>/dev/null || echo 0)"
  if [[ "$pending" -lt 1 ]]; then
    gen_err "steps-backlog.json has no steps"
    fail=1
  fi

  dupes="$(jq -r '.steps[]?.id // empty' "$STEPS_BACKLOG" | sort | uniq -d)"
  if [[ -n "$dupes" ]]; then
    gen_err "duplicate step ids found: $(echo "$dupes" | tr '\n' ' ')"
    fail=1
  fi

  unknown_kinds="$(jq -r '.steps[]? | select((.kind != "agent") and (.kind != "gate") and (.kind != "scaffold")) | .id' "$STEPS_BACKLOG")"
  if [[ -n "$unknown_kinds" ]]; then
    gen_err "steps with unknown kind: $(echo "$unknown_kinds" | tr '\n' ' ')"
    fail=1
  fi
fi

gen_step "Self-check: shell syntax"
while IFS= read -r script; do
  [[ -z "$script" ]] && continue
  if ! bash -n "$script" >/dev/null 2>&1; then
    gen_err "bash syntax error: ${script}"
    fail=1
  fi
done < <(rg --files "${GEN_SCRIPTS_DIR}" -g "*.sh")

if [[ "$fail" -ne 0 ]]; then
  gen_err "Generator self-check failed"
  exit 1
fi

gen_ok "Generator self-check passed"
exit 0
