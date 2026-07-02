#!/usr/bin/env bash
# Fail when repo artifacts reference generator/ paths
# Usage: verify-no-generator-refs.sh [repo-relative-path...]
#        verify-no-generator-refs.sh --scan-docs
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

fail=0

scan_file() {
  local abs="$1"
  local rel="${abs#${REPO_ROOT}/}"
  [[ -f "$abs" ]] || return 0
  if grep -qE 'generator/' "$abs" 2>/dev/null; then
    gen_err "${rel}: references generator/ (forbidden in repo artifacts)"
    fail=1
  fi
}

if [[ "${1:-}" == "--scan-docs" ]]; then
  for dir in docs/brds docs/technical docs/ui-ux ai-harness; do
    root="$(resolve_repo_path "$dir")"
    [[ -d "$root" ]] || continue
    while IFS= read -r f; do
      scan_file "$f"
    done < <(find "$root" -type f \( -name '*.md' -o -name '*.json' \) 2>/dev/null)
  done
  if [[ -f "${REPO_ROOT}/package.json" ]]; then
    scan_file "${REPO_ROOT}/package.json"
  fi
  if [[ -f "${REPO_ROOT}/.gitignore" ]]; then
    scan_file "${REPO_ROOT}/.gitignore"
  fi
elif [[ $# -eq 0 ]]; then
  gen_err "verify-no-generator-refs: no paths provided"
  exit 1
else
  for rel in "$@"; do
    scan_file "$(resolve_repo_path "$rel")"
  done
fi

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi

gen_ok "no-generator-refs ok"
exit 0
