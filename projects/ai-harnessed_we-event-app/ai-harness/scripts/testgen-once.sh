#!/usr/bin/env bash
# Single TestGen iteration — generate test cases for one product item
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/doc-fingerprint.sh
source "$(dirname "$0")/lib/doc-fingerprint.sh"

require_harness_deps
cd "$REPO_ROOT"

if all_test_cases_current; then
  echo "TESTGEN_COMPLETE"
  exit 0
fi

REQUIREMENT_TAG="${1:-$(pick_next_testgen_requirement_tag)}"
if [[ -z "$REQUIREMENT_TAG" ]]; then
  echo "TESTGEN_COMPLETE"
  exit 0
fi

echo "==> TestGen iteration: requirementTag=${REQUIREMENT_TAG}"

RID="$(run_id)"
ensure_runs_dir
mkdir -p "${TEST_CASES_DIR}/items"

set +e
./ai-harness/scripts/check-test-case-drift.sh "$REQUIREMENT_TAG" 2>&1
drift_status=$?
set -e
if [[ "$drift_status" -ne 0 ]]; then
  echo "==> Doc drift reset applied for ${REQUIREMENT_TAG}"
fi

DOC_FP="$(compute_requirement_tag_doc_fingerprint "$REQUIREMENT_TAG")"
ARTIFACT="$(test_case_artifact_abs "$REQUIREMENT_TAG")"

if [[ "${AIH_SKIP_TESTGEN_AGENT:-}" == "1" ]]; then
  echo "WARN: AIH_SKIP_TESTGEN_AGENT=1 — skipping testgen agent"
  agent_out="${RUNS_DIR}/${RID}-testgen.txt"
  echo "TESTGEN_DONE ${REQUIREMENT_TAG}" > "$agent_out"
else
  require_agent
  prompt="$(./ai-harness/scripts/build-prompt.sh testgen "$REQUIREMENT_TAG")"
  model="$(get_model testgen)"
  agent_out="${RUNS_DIR}/${RID}-testgen.txt"

  full_prompt="${prompt}

## Harness reminder

Write the test case JSON artifact to exactly: \`${ARTIFACT}\`
Use doc fingerprint exactly: \`${DOC_FP}\`
Set productItemId to exactly: \`${REQUIREMENT_TAG}\`
Do not edit any other files.

After writing the artifact, end with: TESTGEN_DONE ${REQUIREMENT_TAG}
"

  echo "==> Running testgen agent (${AGENT_BIN}, model=${model})"
  set +e
  agent_invoke_testgen "$model" "$full_prompt" "$agent_out"
  agent_status=$?
  set -e
  echo "==> Agent exit: ${agent_status}"
fi

agent_text="$(cat "$agent_out")"
if echo "$agent_text" | grep -q "TESTGEN_BLOCKED"; then
  reason="$(echo "$agent_text" | grep "TESTGEN_BLOCKED" | tail -1)"
  append_guardrail "$REQUIREMENT_TAG" "$reason"
  append_progress "$REQUIREMENT_TAG" "testgen_blocked"
  echo "TestGen blocked. See guardrails.md"
  exit 1
fi

if ! echo "$agent_text" | grep -q "TESTGEN_DONE"; then
  append_guardrail "$REQUIREMENT_TAG" "TestGen agent did not emit TESTGEN_DONE"
  append_progress "$REQUIREMENT_TAG" "testgen_failed"
  echo "ERROR: TestGen agent did not signal TESTGEN_DONE" >&2
  exit 1
fi

echo "==> Validating test cases"
set +e
validate_out="$(./ai-harness/scripts/validate-test-cases.sh "$REQUIREMENT_TAG" 2>&1)"
validate_status=$?
set -e
echo "$validate_out"

if [[ "$validate_status" -ne 0 ]]; then
  append_guardrail "$REQUIREMENT_TAG" "Test case validation failed — see ${RID}-testgen.txt"
  append_progress "$REQUIREMENT_TAG" "testgen_validation_failed"
  exit 1
fi

./ai-harness/scripts/sync-test-cases-to-backlog.sh "$REQUIREMENT_TAG"

mark_test_cases_current "$REQUIREMENT_TAG" "$DOC_FP"
requeue_slices_pending_test_verification "$REQUIREMENT_TAG"
append_progress "$REQUIREMENT_TAG" "testgen_passed"

commit_on_pass="$(jq -r '.loop.commitOnPass // true' "$TESTGEN_CONFIG")"
if [[ "$commit_on_pass" == "true" ]]; then
  "$(dirname "$0")/git-commit-testgen.sh" "$REQUIREMENT_TAG"
fi

if all_test_cases_current; then
  echo "TESTGEN_COMPLETE"
else
  echo "Test cases generated for ${REQUIREMENT_TAG}. Next: $(pick_next_testgen_requirement_tag)"
fi
