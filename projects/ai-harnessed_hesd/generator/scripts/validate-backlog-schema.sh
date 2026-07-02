#!/usr/bin/env bash
# Validate whole-app-backlog.json shape
# Usage: validate-backlog-schema.sh [path]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

file="${1:-${REPO_ROOT}/ai-harness/whole-app-backlog.json}"
schema="${GEN_ROOT}/schemas/whole-app-backlog.schema.json"

if [[ ! -f "$file" ]]; then
  gen_err "missing backlog: $file"
  exit 1
fi

jq empty "$file" || { gen_err "invalid JSON"; exit 1; }

for field in branchName slices; do
  if [[ "$(jq -r "has(\"$field\")" "$file")" != "true" ]]; then
    gen_err "missing field: $field"
    exit 1
  fi
done

count="$(jq '.slices | length' "$file")"
if [[ "$count" -lt 1 ]]; then
  gen_err "backlog has no slices"
  exit 1
fi

gen_ok "backlog schema valid ($count slices)"
exit 0
