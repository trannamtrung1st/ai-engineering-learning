#!/usr/bin/env bash
# Stage and commit only ManualsGen-owned paths for a backlog item.
# Usage: git-commit-manualsgen.sh <manualItemId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

ITEM_ID="${1:?manual item id required}"
cd "$REPO_ROOT"

if declare -f git_commit_manualsgen_pass >/dev/null 2>&1; then
  git_commit_manualsgen_pass "$ITEM_ID"
  exit 0
fi

paths=(
  "$(manual_artifact_path "$ITEM_ID")"
  "docs/user-manuals/README.md"
  "ai-harness/manuals-index.json"
  "ai-harness/state/progress.md"
)

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

to_add=()
rel
for rel in "${paths[@]}"; do
  [[ -n "$rel" ]] || continue
  [[ -e "$REPO_ROOT/$rel" ]] || continue
  if [[ -e "$REPO_ROOT/$rel" ]] && ! git ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
    to_add+=("$rel")
    continue
  fi
  if ! git diff --quiet -- "$rel" 2>/dev/null; then
    to_add+=("$rel")
    continue
  fi
  if ! git diff --cached --quiet -- "$rel" 2>/dev/null; then
    to_add+=("$rel")
  fi
done

[[ ${#to_add[@]} -gt 0 ]] || exit 0
git add -- "${to_add[@]}"
git commit -m "aih: generate user manual for ${ITEM_ID}" --no-verify 2>/dev/null || true
