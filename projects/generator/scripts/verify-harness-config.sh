#!/usr/bin/env bash
# Validate harness JSON configs against schemas and doc paths
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

fail=0
backlog="${REPO_ROOT}/ai-harness/whole-app-backlog.json"
context_map="${REPO_ROOT}/ai-harness/config/context-map.json"
testgen_map="${REPO_ROOT}/ai-harness/config/testgen-docs-map.json"
manualsgen_map="${REPO_ROOT}/ai-harness/config/manualsgen-docs-map.json"
manuals_backlog="${REPO_ROOT}/ai-harness/manuals-backlog.json"
manuals_index="${REPO_ROOT}/ai-harness/manuals-index.json"

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

if [[ -f "$manuals_backlog" ]]; then
  validate_json_shape "$manuals_backlog" "${GEN_ROOT}/schemas/manuals-backlog.schema.json"
fi

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

if [[ -f "$manualsgen_map" ]]; then
  while IFS= read -r doc; do
    [[ -z "$doc" ]] && continue
    if [[ ! -f "$(resolve_repo_path "$doc")" ]]; then
      gen_err "manualsgen-docs-map path missing: $doc"
      fail=1
    fi
  done < <(jq -r '
    [.alwaysRead[]?, .typeRules[].docs[]?] | unique | .[]
  ' "$manualsgen_map" 2>/dev/null)
fi

if [[ -f "$manuals_backlog" ]]; then
  while IFS= read -r doc; do
    [[ -z "$doc" ]] && continue
    if [[ ! -f "$(resolve_repo_path "$doc")" ]]; then
      gen_err "manuals-backlog sourceDocs path missing: $doc"
      fail=1
    fi
  done < <(jq -r '.items[].sourceDocs[]?' "$manuals_backlog" 2>/dev/null | sort -u)

  flow_count=0
  runbook_count=0
  while IFS= read -r item_type; do
    [[ -z "$item_type" ]] && continue
    if [[ "$item_type" == "flow" ]]; then
      flow_count=$((flow_count + 1))
    elif [[ "$item_type" == "runbook" ]]; then
      runbook_count=$((runbook_count + 1))
    fi
  done < <(jq -r '.items[].type' "$manuals_backlog" 2>/dev/null)

  if [[ "$flow_count" -lt 1 ]]; then
    gen_err "manuals-backlog must include at least one flow item"
    fail=1
  fi
  if [[ "$runbook_count" -ne 1 ]]; then
    gen_err "manuals-backlog must include exactly one runbook item"
    fail=1
  fi

  while IFS= read -r output_path; do
    [[ -z "$output_path" ]] && continue
    if [[ "$output_path" != docs/user-manuals/* ]]; then
      gen_err "manuals-backlog outputPath must be under docs/user-manuals/: ${output_path}"
      fail=1
    fi
  done < <(jq -r '.items[].outputPath' "$manuals_backlog" 2>/dev/null)
fi

if [[ -f "$manuals_index" ]]; then
  if ! jq empty "$manuals_index" 2>/dev/null; then
    gen_err "invalid JSON: $manuals_index"
    fail=1
  fi
fi

if [[ "$fail" -eq 0 ]]; then
  gen_ok "harness-config: valid"
fi
exit "$fail"
