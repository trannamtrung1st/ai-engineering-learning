#!/usr/bin/env bash
# AI code review via Cursor CLI
# Usage: run-ai-review.sh <sliceId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
require_agent

SLICE_ID="${1:-$(pick_next_slice_id)}"
if [[ -z "$SLICE_ID" ]]; then
  echo "ERROR: no slice to review" >&2
  exit 1
fi
RID="$(run_id)"
ensure_runs_dir

cd "$REPO_ROOT"

prompt="$(./ai-harness/scripts/build-prompt.sh "$SLICE_ID" reviewer)"

# Include recent diff context
diff_context=""
if git rev-parse --git-dir >/dev/null 2>&1; then
  diff_context="$(git diff HEAD 2>/dev/null | head -c 50000 || true)"
fi

full_prompt="${prompt}

## Git diff (truncated)

\`\`\`diff
${diff_context}
\`\`\`
"

outfile="${RUNS_DIR}/${RID}-review.txt"
model="$(get_model reviewer)"

set +e
agent_invoke "$model" "$full_prompt" "$outfile"
agent_status=$?
set -e

review_text="$(cat "$outfile")"
echo "$review_text"

review_pass=false
if echo "$review_text" | grep -q 'REVIEW_PASS'; then
  review_pass=true
fi

report="$(jq -n \
  --arg slice "$SLICE_ID" \
  --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
  --argjson pass "$([ "$review_pass" = true ] && echo true || echo false)" \
  --arg agentStatus "$agent_status" \
  '{slice: $slice, timestamp: $ts, pass: $pass, agentExitCode: ($agentStatus | tonumber)}')"

write_run_report "${RID}-review.json" "$report"

if [[ "$review_pass" == true && "$agent_status" -eq 0 ]]; then
  exit 0
fi
exit 1
