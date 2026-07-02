#!/usr/bin/env bash
# Verify markdown doc structure against doc-outlines.json
# Usage: verify-doc-structure.sh <relative-path> [relative-path...]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

fail=0

check_file() {
  local rel="$1"
  local abs outline
  abs="$(resolve_repo_path "$rel")"

  if [[ ! -f "$abs" ]]; then
    gen_err "missing file: $rel"
    fail=1
    return
  fi

  outline="$(jq -r --arg p "$rel" '.[$p] // empty' "$DOC_OUTLINES")"
  if [[ -z "$outline" || "$outline" == "null" ]]; then
    gen_ok "doc-structure: $rel (no outline — skip)"
    return
  fi

  local min_lines
  min_lines="$(echo "$outline" | jq -r '.minLines // 0')"
  local line_count
  line_count="$(wc -l < "$abs" | tr -d ' ')"
  if [[ "$min_lines" -gt 0 && "$line_count" -lt "$min_lines" ]]; then
    gen_err "$rel: only $line_count lines (min $min_lines)"
    fail=1
  fi

  local heading
  while IFS= read -r heading; do
    [[ -z "$heading" ]] && continue
    if ! grep -qi "$heading" "$abs"; then
      gen_err "$rel: missing required heading/substring: $heading"
      fail=1
    fi
  done < <(echo "$outline" | jq -r '.requiredHeadings[]? // empty')

  local sub
  while IFS= read -r sub; do
    [[ -z "$sub" ]] && continue
    if ! grep -qi "$sub" "$abs"; then
      gen_err "$rel: missing required substring: $sub"
      fail=1
    fi
  done < <(echo "$outline" | jq -r '.requiredSubstrings[]? // empty')
}

for rel in "$@"; do
  [[ -z "$rel" ]] && continue
  check_file "$rel"
done

exit "$fail"
