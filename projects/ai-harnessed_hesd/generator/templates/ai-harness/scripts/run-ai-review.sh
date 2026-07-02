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
scope_gate_status="not_run"
scope_gate_note=""
allowlisted_files=""
browser_owned_files=""

if git rev-parse --git-dir >/dev/null 2>&1; then
  allowlist_arr=()
  while IFS= read -r _al_entry; do
    [[ -z "$_al_entry" ]] && continue
    allowlist_arr+=("$_al_entry")
  done < <(build_slice_scope_allowlist "$SLICE_ID" 2>/dev/null || true)
  if [[ ${#allowlist_arr[@]} -gt 0 ]]; then
    allowlisted_files="$(printf '%s\n' "${allowlist_arr[@]}" | sed 's/^/- /')"
    browser_owned_files="$(browser_test_owned_paths "$SLICE_ID" "$RUN_ID" | sed 's/^/- /')"
    while IFS= read -r f; do
      [[ -z "$f" ]] && continue
      if path_in_scope_allowlist "$f" "${allowlist_arr[@]}"; then
        changed_files+="- ${f}"$'\n'
      fi
    done < <(git_changed_files)

    # Trust the implementer scope gate from this run (runs before browser test).
    scope_json="${RUNS_DIR}/${RUN_ID:-$RID}-scope.json"
    if [[ -n "$RUN_ID" && -f "$scope_json" ]] && jq -e '.pass == true' "$scope_json" >/dev/null 2>&1; then
      scope_gate_status="pass"
      scope_gate_note="Implementer scope passed in run ${RUN_ID} before browser test. Browser-test-owned paths below are excluded from scope re-check."
    else
      scope_violations="$(check_slice_scope_violations "$SLICE_ID" true 2>/dev/null || true)"
      if [[ -z "$scope_violations" ]]; then
        scope_gate_status="pass"
        scope_gate_note="No out-of-scope implementer edits detected (browser-test-owned paths excluded)."
      else
        scope_gate_status="fail"
        scope_gate_note="Out-of-scope paths: $(echo "$scope_violations" | tr '\n' ', ' | sed 's/, $//')"
      fi
    fi
    diff_context="$(git diff HEAD -- "${allowlist_arr[@]}" 2>/dev/null | head -c 50000 || true)"
  else
    diff_context="$(git diff HEAD 2>/dev/null | head -c 50000 || true)"
    changed_files="$(git_changed_files | sed 's/^/- /')"
  fi
fi

checks_summary="$(find_checks_report_for_slice "$SLICE_ID" "$RUN_ID")"
browser_test_summary="$(find_browser_test_report_for_slice "$SLICE_ID" "$RUN_ID")"
artifacts_list="$(get_slice_json "$SLICE_ID" | jq -r '.completionArtifacts[]? | "- " + .' 2>/dev/null || true)"

full_prompt="${prompt}

## Harness reminder

Computational checks already passed. Implementer scope gate ran **before** computational checks and browser test in this loop. Browser-test-owned paths (regression index, Playwright spec, UX bugs) are committed by the harness after browser test — **do not** treat them as implementer scope violations. Review **only** from the evidence below and by reading listed files. Do not run shell, npm, docker, tests, builds, servers, or browser/MCP.

## Scope gate

- **scope_gate:** ${scope_gate_status}
- **note:** ${scope_gate_note:-_(not computed)_}
- **allowlisted_files:**

${allowlisted_files:-_(not computed)_}

- **browser_test_owned (excluded from implementer scope):**

${browser_owned_files:-_(none)_}

When scope_gate is \`pass\`, checklist item 1 trusts the allowlisted files list — focus on acceptance and craft only. Never \`REVIEW_FAIL\` solely because \`ai-harness/playwright-regression-index.json\` differs after browser test.

## Changed files (allowlisted only)

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
