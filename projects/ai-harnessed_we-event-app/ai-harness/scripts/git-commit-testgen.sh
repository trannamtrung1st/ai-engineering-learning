#!/usr/bin/env bash
# Stage and commit only TestGen-owned paths for a requirement tag.
# Usage: git-commit-testgen.sh <requirementTag>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

REQUIREMENT_TAG="${1:?requirement tag required}"
cd "$REPO_ROOT"

if declare -f git_commit_testgen_pass >/dev/null 2>&1; then
  git_commit_testgen_pass "$REQUIREMENT_TAG"
  exit 0
fi

# Fallback when common.sh predates git_commit_testgen_pass (parallel agent runs / stale checkout).
paths=(
  "$(test_case_artifact_path "$REQUIREMENT_TAG")"
  "ai-harness/test-cases/items/${REQUIREMENT_TAG}.stale.json"
  "ai-harness/test-case-index.json"
  "ai-harness/whole-app-backlog.json"
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
git commit -m "aih: generate test cases for ${REQUIREMENT_TAG}" --no-verify 2>/dev/null || true
