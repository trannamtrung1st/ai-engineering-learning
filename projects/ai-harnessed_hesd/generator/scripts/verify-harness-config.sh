#!/usr/bin/env bash
# Validate harness JSON configs against schemas and doc paths
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

fail=0
backlog="${REPO_ROOT}/ai-harness/whole-app-backlog.json"
context_map="${REPO_ROOT}/ai-harness/config/context-map.json"
testgen_map="${REPO_ROOT}/ai-harness/config/testgen-docs-map.json"

validate_json_shape() {
  local file="$1"
  local schema="$2"
  if [[ ! -f "$file" ]]; then
    gen_err "missing: $file"
    fail=1
    return
  fi
  if ! jq empty "$file" 2>/dev/null; then
    gen_err "invalid JSON: $file"
    fail=1
    return
  fi
  local required
  required="$(jq -r '.required[]?' "$schema" 2>/dev/null || true)"
  local field
  for field in $required; do
    if [[ "$(jq -r --arg f "$field" 'has($f)' "$file")" != "true" ]]; then
      gen_err "$file: missing required field $field"
      fail=1
    fi
  done
}

validate_json_shape "$backlog" "${GEN_ROOT}/schemas/whole-app-backlog.schema.json"
validate_json_shape "$context_map" "${GEN_ROOT}/schemas/context-map.schema.json"

if [[ -f "$backlog" ]]; then
  brd_tags=""
  for f in docs/brds/03-functional-requirements.md docs/brds/04-business-rules.md \
           docs/brds/07-non-functional-risk.md docs/brds/08-acceptance-mvp-future.md; do
    abs="$(resolve_repo_path "$f")"
    [[ -f "$abs" ]] || continue
    brd_tags="${brd_tags}
$(grep -oE '(FR|BR|NFR|AC)-[0-9]{2}' "$abs" 2>/dev/null || true)"
  done

  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    if ! echo "$brd_tags" | grep -q "$tag"; then
      gen_err "backlog references unknown tag: $tag"
      fail=1
    fi
  done < <(jq -r '.slices[].acceptance[]?' "$backlog" 2>/dev/null | sort -u)

  while IFS= read -r doc; do
    [[ -z "$doc" ]] && continue
    if [[ ! -f "$(resolve_repo_path "$doc")" ]]; then
      gen_err "backlog doc path missing: $doc"
      fail=1
    fi
  done < <(jq -r '.slices[].docs[]?' "$backlog" 2>/dev/null | sort -u)
fi

if [[ -f "$context_map" ]]; then
  while IFS= read -r doc; do
    [[ -z "$doc" ]] && continue
    if [[ ! -f "$(resolve_repo_path "$doc")" ]]; then
      gen_err "context-map doc path missing: $doc"
      fail=1
    fi
  done < <(jq -r '
    [.agents[].alwaysRead[]?, .slices[].docs[]?] | unique | .[]
  ' "$context_map" 2>/dev/null)
fi

if [[ -f "$testgen_map" ]]; then
  while IFS= read -r doc; do
    [[ -z "$doc" ]] && continue
    if [[ ! -f "$(resolve_repo_path "$doc")" ]]; then
      gen_err "testgen-docs-map path missing: $doc"
      fail=1
    fi
  done < <(jq -r '
    [.alwaysRead[]?, .rules[].docs[]?] | unique | .[]
  ' "$testgen_map" 2>/dev/null)
fi

if [[ "$fail" -eq 0 ]]; then
  gen_ok "harness-config: valid"
fi
exit "$fail"
