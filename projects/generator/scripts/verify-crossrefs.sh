#!/usr/bin/env bash
# Verify docs/... cross-references resolve to existing files
# Usage: verify-crossrefs.sh [--allow-missing prefix...] [root-dir-relative...]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

fail=0
roots=()
allow_missing=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-missing)
      shift
      while [[ $# -gt 0 && "$1" != "--" ]]; do
        allow_missing+=("$1")
        shift
      done
      [[ "${1:-}" == "--" ]] && shift
      ;;
    *)
      roots+=("$1")
      shift
      ;;
  esac
done
if [[ ${#roots[@]} -eq 0 ]]; then
  roots=(docs/brds docs/technical docs/ui-ux ai-harness/config)
fi

is_allowed_missing() {
  local ref="$1"
  local prefix
  [[ ${#allow_missing[@]} -eq 0 ]] && return 1
  for prefix in "${allow_missing[@]}"; do
    [[ "$ref" == "$prefix" || "$ref" == "$prefix/"* ]] && return 0
  done
  return 1
}

is_template_ref() {
  local ref="$1"
  [[ "$ref" == *'YYYY'* ]] && return 0
  [[ "$ref" == *'<'* || "$ref" == *'>'* ]] && return 0
  [[ "$ref" == *'*'* ]] && return 0
  [[ "$ref" == *'{{'* ]] && return 0
  return 1
}

scan_file() {
  local file="$1"
  local ref abs alt
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    [[ "$ref" == *'<'* || "$ref" == *'>'* ]] && continue
    ref="${ref%%#*}"
    ref="${ref%%\?*}"
    abs="$(resolve_repo_path "$ref")"
    if [[ -f "$abs" || -d "$abs" ]]; then
      continue
    fi
    # Harness docs are sometimes referenced as docs/*.md
    alt=""
    case "$ref" in
      docs/preview-runtime.md|docs/browser-mcp.md)
        alt="ai-harness/${ref#docs/}"
        alt="ai-harness/docs/$(basename "$ref")"
        ;;
    esac
    if [[ -n "$alt" && ( -f "$(resolve_repo_path "$alt")" || -d "$(resolve_repo_path "$alt")" ) ]]; then
      continue
    fi
    if [[ "$ref" == ai-harness/* ]]; then
      continue
    fi
    if is_allowed_missing "$ref"; then
      continue
    fi
    if is_template_ref "$ref"; then
      continue
    fi
    gen_err "$file: unresolved reference: $ref"
    fail=1
  done < <(
    grep -oE '`docs/[^`]+`|docs/[a-zA-Z0-9_./-]+\.md' "$file" 2>/dev/null \
      | tr -d '`' \
      | sort -u || true
  )
}

for root in "${roots[@]}"; do
  abs_root="$(resolve_repo_path "$root")"
  if [[ -d "$abs_root" ]]; then
    while IFS= read -r f; do
      scan_file "$f"
    done < <(find "$abs_root" -type f \( -name '*.md' -o -name '*.json' \) 2>/dev/null)
  elif [[ -f "$abs_root" ]]; then
    scan_file "$abs_root"
  fi
done

if [[ "$fail" -eq 0 ]]; then
  gen_ok "crossrefs: all resolved"
fi
exit "$fail"
