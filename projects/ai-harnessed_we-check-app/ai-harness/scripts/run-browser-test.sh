#!/usr/bin/env bash
# Browser functional/UI test via Playwright MCP
# Usage: run-browser-test.sh <sliceId> [runId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
require_agent

SLICE_ID="${1:-$(pick_next_slice_id)}"
RUN_ID="${2:-${AIH_RUN_ID:-}}"
if [[ -z "$SLICE_ID" ]]; then
  echo "ERROR: no slice to test" >&2
  exit 1
fi
RID="${RUN_ID:-$(run_id)}"
ensure_runs_dir

cd "$REPO_ROOT"

browser_test_required() {
  jq -r '.browserTest.required // true' "$LOOP_CONFIG"
}

write_skipped_report() {
  local reason="$1"
  local report
  report="$(jq -n \
    --arg slice "$SLICE_ID" \
    --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg reason "$reason" \
    '{slice: $slice, timestamp: $ts, pass: true, skipped: true, reason: $reason}')"
  write_run_report "${RID}-browser-test.json" "$report"
  echo "$report"
}

if ! slice_requires_browser_test "$SLICE_ID"; then
  echo "==> Browser test skipped (agent not in activeWhenAgent): ${SLICE_ID}"
  write_skipped_report "agent not in browserTest.activeWhenAgent"
  exit 0
fi

if [[ "$(browser_test_required)" != "true" ]]; then
  echo "==> Browser test skipped (browserTest.required=false)"
  write_skipped_report "browserTest.required is false"
  exit 0
fi

cleanup_playwright_mcp_artifacts
ensure_screenshot_dir "$(screenshot_dir_for_slice "$SLICE_ID" browser-test)"

require_preview="$(jq -r '.browserTest.requirePreviewStack // true' "$LOOP_CONFIG")"
if [[ "$require_preview" == "true" ]]; then
  echo "==> Verifying preview stack before browser test"
  set +e
  ensure_preview_stack_for_browser_test
  stack_status=$?
  set -e
  if [[ "$stack_status" -ne 0 ]]; then
    report="$(jq -n \
      --arg slice "$SLICE_ID" \
      --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
      '{slice: $slice, timestamp: $ts, pass: false, skipped: false, reason: "preview stack verification failed"}')"
    write_run_report "${RID}-browser-test.json" "$report"
    exit 1
  fi
fi

prompt="$(./ai-harness/scripts/build-prompt.sh "$SLICE_ID" tester)"

changed_files=""
checks_summary=""
artifacts_list=""
acceptance_tags=""
slice_json="$(get_slice_json "$SLICE_ID")"

if git rev-parse --git-dir >/dev/null 2>&1; then
  changed_files="$(git_changed_files | sed 's/^/- /')"
fi

checks_summary="$(find_checks_report_for_slice "$SLICE_ID" "$RUN_ID")"
artifacts_list="$(echo "$slice_json" | jq -r '.completionArtifacts[]? | "- " + .' 2>/dev/null || true)"
acceptance_tags="$(echo "$slice_json" | jq -r '.acceptance[]? | "- " + .' 2>/dev/null || true)"

generated_browser_cases=""
test_cases_json=""
if slice_test_cases_current "$SLICE_ID"; then
  test_cases_json="$(load_test_cases_json_for_slice "$SLICE_ID" | jq -c '.')"
  generated_browser_cases="$(load_test_cases_json_for_slice "$SLICE_ID" | jq -r '
    .cases[]? | select(.layer == "browser")
    | "- **\(.id)** [\(.category)/\(.priority)]: \(.title)\n  Product: \(.traceability | join(", "))\n  Preconditions: \(.preconditions | join("; "))\n  Steps: \(.steps | join(" → "))\n  Expected: \(.expected)"
  ' 2>/dev/null || true)"
fi

WEB_PORT="${AIH_PREVIEW_WEB_PORT:-3000}"
API_PORT="${AIH_PREVIEW_API_PORT:-3001}"

full_prompt="${prompt}

## Harness reminder

Computational checks already passed. Use **Playwright MCP** to verify acceptance criteria in the browser. Do not edit files or re-run npm test/build scripts.

## Preview stack

- Web: http://localhost:${WEB_PORT}
- API health: http://localhost:${API_PORT}/api/v1/health
- Dev auth: see docs/technical/10-local-development-setup.md

## Changed files (context only — do not edit)

${changed_files:-_(none detected)_}

## Completion artifacts

${artifacts_list:-_(none listed)_}

## Slice acceptance tags (derive browser scenarios from artifacts when no browser cases below)

${acceptance_tags:-_(none listed)_}

## Generated browser test cases (mandatory — from docs/test-cases/items/<tag>.json via acceptance)

${generated_browser_cases:-_(no browser-layer cases in current artifacts for this slice — derive scenarios from acceptance tags, slice description, and docs above)_}

## Full test case artifact (reference)

\`\`\`json
${test_cases_json:-{}}
\`\`\`

## Computational checks (already passed — trust this)

\`\`\`json
${checks_summary}
\`\`\`
"

outfile="${RUNS_DIR}/${RID}-browser-test.txt"
model="$(get_model tester)"

aih_step "Running browser test agent (${AGENT_BIN}, model=${model})"
aih_agent_begin "tester (${model})"
set +e
agent_invoke_browser_test "$model" "$full_prompt" "$outfile"
agent_status=$?
set -e
aih_agent_end "${agent_status}"

test_text="$(cat "$outfile")"
if ! agent_stream_enabled; then
  echo "$test_text"
fi

test_pass=false
if echo "$test_text" | grep -q 'BROWSER_TEST_PASS'; then
  test_pass=true
fi

timed_out=false
timeout_reason=""
if [[ "$agent_status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
  timed_out=true
  timeout_ms="$(get_agent_timeout_ms "$LOOP_CONFIG")"
  timeout_reason="Agent timed out after ${timeout_ms}ms"
fi

report="$(jq -n \
  --arg slice "$SLICE_ID" \
  --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
  --argjson pass "$([ "$test_pass" = true ] && echo true || echo false)" \
  --argjson skipped false \
  --argjson timedOut "$timed_out" \
  --arg reason "$timeout_reason" \
  --arg agentStatus "$agent_status" \
  '{slice: $slice, timestamp: $ts, pass: $pass, skipped: $skipped, timedOut: $timedOut, reason: (if $reason == "" then null else $reason end), agentExitCode: ($agentStatus | tonumber)}')"

write_run_report "${RID}-browser-test.json" "$report"

if [[ "$test_pass" == true && "$agent_status" -eq 0 ]]; then
  exit 0
fi
exit 1
