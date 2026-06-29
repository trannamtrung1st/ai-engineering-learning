#!/usr/bin/env bash
# AI code review via Cursor CLI (read-only static pass)
# Usage: run-ai-review.sh <sliceId> [runId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
require_agent

SLICE_ID="${1:-$(pick_next_slice_id)}"
RUN_ID="${2:-${AIH_RUN_ID:-}}"
if [[ -z "$SLICE_ID" ]]; then
  echo "ERROR: no slice to review" >&2
  exit 1
fi
RID="$(run_id)"
ensure_runs_dir

cd "$REPO_ROOT"

prompt="$(./ai-harness/scripts/build-prompt.sh "$SLICE_ID" reviewer)"

# Bundle static evidence so the reviewer does not need to run checks.
diff_context=""
changed_files=""
checks_summary=""
artifacts_list=""

if git rev-parse --git-dir >/dev/null 2>&1; then
  diff_context="$(git diff HEAD 2>/dev/null | head -c 50000 || true)"
  changed_files="$(git_changed_files | sed 's/^/- /')"
fi

checks_summary="$(find_checks_report_for_slice "$SLICE_ID" "$RUN_ID")"
browser_test_summary="$(find_browser_test_report_for_slice "$SLICE_ID" "$RUN_ID")"
artifacts_list="$(get_slice_json "$SLICE_ID" | jq -r '.completionArtifacts[]? | "- " + .' 2>/dev/null || true)"

full_prompt="${prompt}

## Harness reminder

Computational checks already passed. Browser functional test report is bundled below when applicable. Review **only** from the evidence below and by reading listed files. Do not run shell, npm, docker, tests, builds, servers, or browser/MCP.

## Changed files (read these + completion artifacts only)

${changed_files:-_(none detected)_}

## Completion artifacts

${artifacts_list:-_(none listed)_}

## Computational checks (already passed — trust this; do not re-run)

\`\`\`json
${checks_summary}
\`\`\`

## Browser functional test (trust when not skipped; do not re-run)

\`\`\`json
${browser_test_summary}
\`\`\`

## Git diff (truncated)

\`\`\`diff
${diff_context}
\`\`\`
"

outfile="${RUNS_DIR}/${RID}-review.txt"
model="$(get_model reviewer)"

aih_agent_begin "reviewer (${model})"
set +e
agent_invoke_review "$model" "$full_prompt" "$outfile"
agent_status=$?
set -e
aih_agent_end "${agent_status}"

review_text="$(cat "$outfile")"
if ! agent_stream_enabled; then
  echo "$review_text"
fi

review_pass=false
if echo "$review_text" | grep -q 'REVIEW_PASS'; then
  review_pass=true
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
  --argjson pass "$([ "$review_pass" = true ] && echo true || echo false)" \
  --argjson timedOut "$timed_out" \
  --arg reason "$timeout_reason" \
  --arg agentStatus "$agent_status" \
  '{slice: $slice, timestamp: $ts, pass: $pass, timedOut: $timedOut, reason: (if $reason == "" then null else $reason end), agentExitCode: ($agentStatus | tonumber)}')"

write_run_report "${RID}-review.json" "$report"

if [[ "$review_pass" == true && "$agent_status" -eq 0 ]]; then
  exit 0
fi
exit 1
