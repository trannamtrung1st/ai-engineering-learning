#!/usr/bin/env bash
# ManualsGen loop — generate user manuals from docs for all backlog items
# Usage: manualsgen-loop.sh [maxIterations]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

if [[ ! -f "$MANUALS_BACKLOG" ]]; then
  aih_err "Missing ${MANUALS_BACKLOG} — run harness planner (harness-context-maps step)"
  exit 1
fi

max="${1:-$(jq -r '.loop.maxIterations // 30' "$MANUALSGEN_CONFIG")}"
iter=0

aih_section "ManualsGen loop (max=${max})" loop
print_harness_env

while [[ "$iter" -lt "$max" ]]; do
  if all_manuals_current; then
    echo "MANUALSGEN_COMPLETE"
    exit 0
  fi

  iter=$((iter + 1))
  aih_section "ManualsGen iteration ${iter}/${max}" iteration

  set +e
  ./ai-harness/scripts/manualsgen-once.sh
  status=$?
  set -e

  if [[ "$status" -ne 0 ]]; then
    aih_warn "ManualsGen iteration ${iter} did not pass; continuing with fresh context"
  fi

  if all_manuals_current; then
    echo "MANUALSGEN_COMPLETE"
    exit 0
  fi
done

aih_err "Max ManualsGen iterations (${max}) reached"
remaining=0
pending=0
item_id=""
while IFS= read -r item_id; do
  [[ -z "$item_id" ]] && continue
  remaining=$((remaining + 1))
  if ! manual_item_current "$item_id"; then
    pending=$((pending + 1))
  fi
done < <(all_manual_item_ids_sorted)
aih_info "Remaining manual items without current docs: ${pending} / ${remaining}"
exit 1
