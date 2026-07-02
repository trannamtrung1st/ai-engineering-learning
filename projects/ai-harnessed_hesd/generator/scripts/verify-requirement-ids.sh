#!/usr/bin/env bash
# Verify requirement ID patterns in doc files
# Usage: verify-requirement-ids.sh [--global] [path...]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

fail=0
global_mode=false
paths=()

for arg in "$@"; do
  case "$arg" in
    --global) global_mode=true ;;
    *) paths+=("$arg") ;;
  esac
done

if [[ "$global_mode" == true ]]; then
  paths=(
    docs/brds/03-functional-requirements.md
    docs/brds/04-business-rules.md
    docs/brds/07-non-functional-risk.md
    docs/brds/08-acceptance-mvp-future.md
  )
fi

check_prefix() {
  local file="$1"
  local prefix="$2"
  local abs
  abs="$(resolve_repo_path "$file")"
  [[ -f "$abs" ]] || return 0

  local ids seen="" dup="" id
  ids="$(grep -oE "${prefix}-[0-9]{2}" "$abs" 2>/dev/null | sort -u || true)"
  if [[ -z "$ids" ]]; then
    gen_err "$file: no ${prefix}-xx IDs found"
    fail=1
    return
  fi

  while IFS= read -r id; do
    [[ -z "$id" ]] && continue
    if echo "$seen" | grep -q "$id"; then
      dup="$id"
    fi
    seen="${seen} ${id}"
  done <<< "$ids"

  if [[ -n "$dup" ]]; then
    gen_err "$file: duplicate ID $dup"
    fail=1
  fi

  gen_ok "requirement-ids: $file (${prefix}-*)"
}

for file in "${paths[@]}"; do
  [[ -z "$file" ]] && continue
  case "$file" in
    *03-functional*) check_prefix "$file" "FR" ;;
    *04-business*) check_prefix "$file" "BR" ;;
    *07-non-functional*) check_prefix "$file" "NFR" ;;
    *08-acceptance*) check_prefix "$file" "AC" ;;
    *)
      for prefix in FR BR NFR AC; do
        abs="$(resolve_repo_path "$file")"
        if [[ -f "$abs" ]] && grep -qE "${prefix}-[0-9]{2}" "$abs" 2>/dev/null; then
          check_prefix "$file" "$prefix"
        fi
      done
      ;;
  esac
done

if [[ "$global_mode" == true ]]; then
  gen_ok "requirement-ids-global: per-file checks complete"
fi

exit "$fail"
