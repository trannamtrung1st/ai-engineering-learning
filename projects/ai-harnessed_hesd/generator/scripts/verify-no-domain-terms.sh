#!/usr/bin/env bash
# Fail when generator templates/agents embed product-specific domain terms.
# Usage: verify-no-domain-terms.sh
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

GENERATOR_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

pattern='\b(admin|instructor|student|participant|organizer|check-in|event-specific)\b'

for root in templates agents; do
  dir="${GENERATOR_ROOT}/${root}"
  [[ -d "$dir" ]] || continue
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    file="${match%%:*}"
    line="${match#*:}"
    rel="${file#${GENERATOR_ROOT}/}"
    if grep -qiE 'never hardcode|do not hardcode|not hardcode|forbidden.*role|avoid.*hardcod' <<<"$line"; then
      continue
    fi
    gen_err "${rel}: forbidden domain term in: ${line}"
    fail=1
  done < <(grep -rniE "$pattern" "$dir" \
    --include='*.md' --include='*.sh' --include='*.json' --include='*.prompt.md' 2>/dev/null || true)
done

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi

gen_ok "no-domain-terms ok"
exit 0
