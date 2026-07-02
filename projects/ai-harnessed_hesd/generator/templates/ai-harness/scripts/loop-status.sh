#!/usr/bin/env bash
# Loop health dashboard — human-readable stdout
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

pending="$(jq '[.slices[] | select(.passes == false)] | length' "$BACKLOG")"
total="$(jq '.slices | length' "$BACKLOG")"
next="$(pick_next_slice_id)"

echo "=== AI Harness status ==="
echo "Slices: ${pending} pending / ${total} total"
echo "Next slice: ${next:-COMPLETE}"

override_info="$(get_loop_slice_override_info)"
override_id="$(echo "$override_info" | jq -r '.nextSliceId // empty')"
if [[ -n "$override_id" && "$override_id" != "null" ]]; then
  override_reason="$(echo "$override_info" | jq -r '.reason // ""')"
  override_set_at="$(echo "$override_info" | jq -r '.setAt // ""')"
  echo "Loop override (one-shot): ${override_id}"
  echo "  reason: ${override_reason}"
  echo "  setAt: ${override_set_at}"
fi

echo ""
echo "Pending slice history (last entry):"
while IFS= read -r slice_id; do
  [[ -z "$slice_id" ]] && continue
  last_history="$(jq -r --arg id "$slice_id" '
    (.slices[] | select(.id == $id) | .history // [])[-1]
    | if . == null then empty else "\(.at) | \(.kind): \(.reason)" end
  ' "$BACKLOG" 2>/dev/null || true)"
  if [[ -n "$last_history" ]]; then
    echo "  ${slice_id}: ${last_history}"
  else
    echo "  ${slice_id}: (no history)"
  fi
done < <(jq -r '.slices[] | select(.passes == false) | .id' "$BACKLOG")

echo ""
echo "Stale test case tags (current: false):"
stale="$(jq -r '.tags | to_entries[] | select(.value.current == false) | .key' "$TEST_CASE_INDEX" 2>/dev/null || true)"
if [[ -z "$stale" ]]; then
  echo "  (none)"
else
  printf '  %s\n' $stale
fi

echo ""
echo "Per-slice iterations since last passed (from progress.md):"
if [[ -f "${STATE_DIR}/progress.md" ]]; then
  while IFS= read -r slice_id; do
    [[ -z "$slice_id" ]] && continue
    count="$(grep -c "| ${slice_id} |" "${STATE_DIR}/progress.md" 2>/dev/null || echo 0)"
    last_pass="$(grep "| ${slice_id} | passed" "${STATE_DIR}/progress.md" 2>/dev/null | tail -1 || true)"
    if [[ -n "$last_pass" ]]; then
      after_pass="$(awk -v s="$slice_id" -v p="$last_pass" '
        $0 == p { found=1; next }
        found && $0 ~ "\\| " s " \\|" { c++ }
        END { print c+0 }
      ' "${STATE_DIR}/progress.md")"
      echo "  ${slice_id}: ${after_pass} since last pass"
    else
      echo "  ${slice_id}: ${count} total entries (never passed)"
    fi
  done < <(jq -r '.slices[] | select(.passes == false) | .id' "$BACKLOG")
else
  echo "  (no progress.md)"
fi

echo ""
echo "Recent gate failures (last 20 progress lines):"
if [[ -f "${STATE_DIR}/progress.md" ]]; then
  grep -E 'scope_failed|review_failed|browser_test_failed|checks_failed' "${STATE_DIR}/progress.md" 2>/dev/null | tail -20 || echo "  (none)"
else
  echo "  (no progress.md)"
fi

echo ""
echo "Latest check duration (from recent *-checks.json):"
latest_check="$(find "${RUNS_DIR}" -maxdepth 1 -name '*-checks.json' -type f 2>/dev/null | sort -r | head -1 || true)"
if [[ -n "$latest_check" && -f "$latest_check" ]]; then
  echo "  $(basename "$latest_check") — slice: $(jq -r '.slice // "?"' "$latest_check") pass: $(jq -r '.pass' "$latest_check")"
  log_guess="${latest_check%-checks.json}"
  for suffix in -check-test-integration.log -check-typecheck.log -check-lint.log -check-test-unit.log -check-test-playwright-ui.log; do
  if [[ -f "${log_guess}${suffix}" ]]; then
    echo "    log: $(basename "${log_guess}${suffix}")"
  fi
  done
else
  echo "  (no check reports found)"
fi
