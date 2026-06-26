#!/usr/bin/env bash
# Ad-hoc TestGen enhancement — improve test cases for one tag with free-text instructions
# Usage: testgen-enhance.sh <REQUIREMENT_TAG> [instructions...]
#        testgen-enhance.sh <REQUIREMENT_TAG> --file <path>
#        testgen-enhance.sh <REQUIREMENT_TAG> --context <path1,path2> [instructions...]
#        testgen-enhance.sh <REQUIREMENT_TAG> --no-commit [instructions...]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/doc-fingerprint.sh
source "$(dirname "$0")/lib/doc-fingerprint.sh"

require_harness_deps
cd "$REPO_ROOT"

NO_COMMIT=false
INSTRUCTION_FILE=""
EXTRA_CONTEXT_RAW=""
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-commit)
      NO_COMMIT=true
      shift
      ;;
    --file)
      INSTRUCTION_FILE="${2:?--file requires a path}"
      shift 2
      ;;
    --context)
      EXTRA_CONTEXT_RAW="${2:?--context requires comma-separated paths}"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage: testgen-enhance.sh <REQUIREMENT_TAG> [options] [instructions...]

Improve test cases for one requirement tag using free-text instructions.

Options:
  --file <path>              Read instructions from a file
  --context <path1,path2>    Extra repo-relative paths for the agent to read
  --no-commit                Skip git commit after a successful run
  -h, --help                 Show this help

Instructions may be passed as remaining arguments or piped on stdin when omitted.

Examples:
  testgen-enhance.sh FR-08 "Add browser-journey cases for admin pagination"
  echo "Tighten preconditions on TC-FR-08-003" | testgen-enhance.sh FR-08
EOF
      exit 0
      ;;
    --)
      shift
      POSITIONAL+=("$@")
      break
      ;;
    -*)
      echo "ERROR: unknown option: $1" >&2
      exit 1
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if [[ ${#POSITIONAL[@]} -lt 1 ]]; then
  echo "ERROR: requirement tag required (e.g. AC-01, FR-08)" >&2
  exit 1
fi

REQUIREMENT_TAG="${POSITIONAL[0]}"
require_valid_requirement_tag "$REQUIREMENT_TAG"

INSTRUCTION_ARGS=()
if [[ ${#POSITIONAL[@]} -gt 1 ]]; then
  INSTRUCTION_ARGS=("${POSITIONAL[@]:1}")
fi

INSTRUCTIONS=""
if [[ -n "$INSTRUCTION_FILE" ]]; then
  if [[ ! -f "$INSTRUCTION_FILE" ]]; then
    echo "ERROR: instruction file not found: $INSTRUCTION_FILE" >&2
    exit 1
  fi
  INSTRUCTIONS="$(cat "$INSTRUCTION_FILE")"
elif [[ ${#INSTRUCTION_ARGS[@]} -gt 0 ]]; then
  INSTRUCTIONS="$(printf '%s ' "${INSTRUCTION_ARGS[@]}")"
  INSTRUCTIONS="${INSTRUCTIONS%" "}"
elif [[ ! -t 0 ]]; then
  INSTRUCTIONS="$(cat)"
fi

if [[ -z "${INSTRUCTIONS//[[:space:]]/}" ]]; then
  echo "ERROR: enhancement instructions required (positional args, --file, or stdin)" >&2
  exit 1
fi

EXTRA_CONTEXT_BLOCK=""
if [[ -n "$EXTRA_CONTEXT_RAW" ]]; then
  IFS=',' read -ra CONTEXT_PATHS <<< "$EXTRA_CONTEXT_RAW"
  for rel in "${CONTEXT_PATHS[@]}"; do
    rel="${rel#"${rel%%[![:space:]]*}"}"
    rel="${rel%"${rel##*[![:space:]]}"}"
    [[ -n "$rel" ]] || continue
    if [[ ! -f "${REPO_ROOT}/${rel}" ]]; then
      echo "ERROR: context path not found: ${rel}" >&2
      exit 1
    fi
    EXTRA_CONTEXT_BLOCK+="- ${rel}"$'\n'
  done
fi

echo "==> TestGen enhance: requirementTag=${REQUIREMENT_TAG}"

RID="$(run_id)"
ensure_runs_dir
mkdir -p "${TEST_CASES_DIR}/items"

DOC_FP="$(compute_requirement_tag_doc_fingerprint "$REQUIREMENT_TAG")"
ARTIFACT="$(test_case_artifact_abs "$REQUIREMENT_TAG")"
ensure_test_case_artifact_restored "$REQUIREMENT_TAG"

if [[ "${AIH_SKIP_TESTGEN_AGENT:-}" == "1" ]]; then
  echo "WARN: AIH_SKIP_TESTGEN_AGENT=1 — skipping testgen agent"
  agent_out="${RUNS_DIR}/${RID}-testgen-enhance.txt"
  echo "TESTGEN_DONE ${REQUIREMENT_TAG}" > "$agent_out"
else
  require_agent
  prompt="$(./ai-harness/scripts/build-prompt.sh testgen "$REQUIREMENT_TAG")"
  enhancement_block="$(format_testgen_enhancement_block "$REQUIREMENT_TAG" "$INSTRUCTIONS" "$EXTRA_CONTEXT_BLOCK")"
  model="$(get_model testgen)"
  agent_out="${RUNS_DIR}/${RID}-testgen-enhance.txt"

  review_reminder=""
  if [[ -f "$ARTIFACT" ]]; then
    review_reminder="
Review and update the existing artifact at \`$(test_case_artifact_path "$REQUIREMENT_TAG")\` — apply enhancement instructions; change only what is needed."
    echo "==> Incremental enhance: existing artifact for ${REQUIREMENT_TAG}"
  fi

  full_prompt="${prompt}

${enhancement_block}

## Harness reminder

Write the test case JSON artifact to exactly: \`${ARTIFACT}\`
Use doc fingerprint exactly: \`${DOC_FP}\`
Set productItemId to exactly: \`${REQUIREMENT_TAG}\`
Do not edit any other files.${review_reminder}

After writing the artifact, end with: TESTGEN_DONE ${REQUIREMENT_TAG}
"

  echo "==> Running testgen enhance agent (${AGENT_BIN}, model=${model})"
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
  append_progress "$REQUIREMENT_TAG" "testgen_enhance_blocked"
  echo "TestGen enhance blocked. See guardrails.md"
  exit 1
fi

if ! echo "$agent_text" | grep -q "TESTGEN_DONE"; then
  append_guardrail "$REQUIREMENT_TAG" "TestGen enhance agent did not emit TESTGEN_DONE"
  append_progress "$REQUIREMENT_TAG" "testgen_enhance_failed"
  echo "ERROR: TestGen enhance agent did not signal TESTGEN_DONE" >&2
  exit 1
fi

echo "==> Validating test cases"
set +e
validate_out="$(./ai-harness/scripts/validate-test-cases.sh "$REQUIREMENT_TAG" 2>&1)"
validate_status=$?
set -e
echo "$validate_out"

if [[ "$validate_status" -ne 0 ]]; then
  append_guardrail "$REQUIREMENT_TAG" "Test case validation failed after enhance — see ${RID}-testgen-enhance.txt"
  append_progress "$REQUIREMENT_TAG" "testgen_enhance_validation_failed"
  exit 1
fi

./ai-harness/scripts/sync-test-cases-to-backlog.sh "$REQUIREMENT_TAG"

mark_test_cases_current "$REQUIREMENT_TAG" "$DOC_FP"
append_progress "$REQUIREMENT_TAG" "testgen_enhance_passed"

should_commit=false
if [[ "$NO_COMMIT" != "true" && "${AIH_TESTGEN_NO_COMMIT:-}" != "1" ]]; then
  commit_on_pass="$(jq -r '.loop.commitOnPass // true' "$TESTGEN_CONFIG")"
  [[ "$commit_on_pass" == "true" ]] && should_commit=true
fi

if [[ "$should_commit" == "true" ]]; then
  "$(dirname "$0")/git-commit-testgen.sh" "$REQUIREMENT_TAG"
fi

echo "Test cases enhanced for ${REQUIREMENT_TAG}"
