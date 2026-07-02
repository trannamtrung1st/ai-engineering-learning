#!/usr/bin/env bash
# Validate generator internals before running loops.
# Usage: self-check.sh
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

fail=0

check_file_exists() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    gen_err "missing required file: ${path}"
    fail=1
  fi
}

check_json() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    gen_err "missing json: ${path}"
    fail=1
    return
  fi
  if ! jq empty "$path" >/dev/null 2>&1; then
    gen_err "invalid json: ${path}"
    fail=1
  fi
}

gen_step "Self-check: required generator files"
check_file_exists "$STEPS_BACKLOG"
check_file_exists "$LOOP_CONFIG"
check_file_exists "$MODELS_CONFIG"
check_file_exists "$DOC_OUTLINES"
check_file_exists "${GEN_ROOT}/schemas/step-backlog.schema.json"
check_file_exists "${GEN_ROOT}/schemas/docs-inventory.schema.json"
check_file_exists "${GEN_ROOT}/agents/doc-writer.prompt.md"
check_file_exists "${GEN_ROOT}/agents/harness-planner.prompt.md"
check_file_exists "${GEN_ROOT}/agents/gate-repair.prompt.md"

gen_step "Self-check: JSON parse"
check_json "$STEPS_BACKLOG"
check_json "$LOOP_CONFIG"
check_json "$MODELS_CONFIG"
check_json "$DOC_OUTLINES"
check_json "${GEN_ROOT}/config/product-meta.schema.json"
check_json "${GEN_ROOT}/schemas/step-backlog.schema.json"
check_json "${GEN_ROOT}/schemas/docs-inventory.schema.json"

gen_step "Self-check: backlog sanity"
if [[ -f "$STEPS_BACKLOG" ]]; then
  pending="$(jq '[.steps[]?] | length' "$STEPS_BACKLOG" 2>/dev/null || echo 0)"
  if [[ "$pending" -lt 1 ]]; then
    gen_err "steps-backlog.json has no steps"
    fail=1
  fi

  dupes="$(jq -r '.steps[]?.id // empty' "$STEPS_BACKLOG" | sort | uniq -d)"
  if [[ -n "$dupes" ]]; then
    gen_err "duplicate step ids found: $(echo "$dupes" | tr '\n' ' ')"
    fail=1
  fi

  unknown_kinds="$(jq -r '.steps[]? | select((.kind != "agent") and (.kind != "gate") and (.kind != "scaffold")) | .id' "$STEPS_BACKLOG")"
  if [[ -n "$unknown_kinds" ]]; then
    gen_err "steps with unknown kind: $(echo "$unknown_kinds" | tr '\n' ' ')"
    fail=1
  fi
fi

gen_step "Self-check: shell syntax"
while IFS= read -r script; do
  [[ -z "$script" ]] && continue
  if ! bash -n "$script" >/dev/null 2>&1; then
    gen_err "bash syntax error: ${script}"
    fail=1
  fi
done < <(rg --files "${GEN_SCRIPTS_DIR}" -g "*.sh")

if [[ "$fail" -ne 0 ]]; then
  gen_err "Generator self-check failed"
  exit 1
fi

gen_ok "Generator self-check passed"
exit 0
