#!/usr/bin/env bash
# Warn-only: verify implementer screenshot dir has evidence for slice routes
# Usage: check-ui-screenshot-evidence.sh <sliceId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

SLICE_ID="${1:?slice id required}"
require_harness_deps
cd "$REPO_ROOT"

agent_type="$(get_slice_field "$SLICE_ID" agent 2>/dev/null || echo backend)"
if [[ "$agent_type" != "frontend" && "$agent_type" != "test" ]]; then
  aih_check_skip "UI screenshot evidence (${SLICE_ID} — not frontend/test)"
  exit 0
fi

dir="$(screenshot_dir_for_slice "$SLICE_ID" implementer)"
route_count=0
while IFS= read -r artifact; do
  [[ -z "$artifact" ]] && continue
  if [[ "$artifact" == apps/web/src/app/*/page.tsx || "$artifact" == apps/web/src/app/* ]]; then
    route_count=$((route_count + 1))
  fi
done < <(get_slice_json "$SLICE_ID" | jq -r '.completionArtifacts[]?')

png_count=0
if [[ -d "$dir" ]]; then
  png_count="$(find "$dir" -maxdepth 1 -name '*.png' 2>/dev/null | wc -l | tr -d ' ')"
fi

aih_check_begin "UI screenshot evidence (${SLICE_ID})"
if [[ "$route_count" -eq 0 ]]; then
  aih_check_skip "no web routes in completionArtifacts"
  exit 0
fi

if [[ "$png_count" -lt "$route_count" ]]; then
  aih_warn "screenshots: ${png_count} png(s) in ${dir}, ~${route_count} route artifact(s) — warn only"
  aih_check_ok "UI screenshot evidence (warn: low count)"
  exit 0
fi

aih_check_ok "UI screenshot evidence (${png_count} png(s))"
exit 0
