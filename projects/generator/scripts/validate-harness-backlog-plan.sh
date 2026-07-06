#!/usr/bin/env bash
# Validate whole-app-backlog plan markdown before harness-planner implements JSON
# Usage: validate-harness-backlog-plan.sh [--quiet]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_gen_deps

QUIET=false
if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=true
fi

log_err() {
  if [[ "$QUIET" == true ]]; then
    echo "$1" >&2
  else
    gen_err "$1"
  fi
}

log_ok() {
  if [[ "$QUIET" != true ]]; then
    gen_ok "$1"
  fi
}

plan_path="$(resolve_repo_path ai-harness/plans/whole-app-backlog.md)"
if [[ ! -f "$plan_path" ]]; then
  log_err "missing plan: ai-harness/plans/whole-app-backlog.md"
  exit 1
fi

FAILURES=()

required_headings=(
  "Product scope and branch"
  "Slice inventory"
  "Acceptance tag mapping"
  "Testing plan cross-walk"
  "Per-slice planning metadata"
  "Risks and open questions"
)

for heading in "${required_headings[@]}"; do
  if ! grep -qiE "^##[[:space:]]+${heading}[[:space:]]*$" "$plan_path"; then
    FAILURES+=("missing required heading: ## ${heading}")
  fi
done

extract_section() {
  local section_title="$1"
  awk -v title="$section_title" '
    BEGIN { in_section=0 }
    /^##[[:space:]]+/ {
      if (in_section) { exit }
      if (tolower($0) ~ ("^##[[:space:]]+" tolower(title) "[[:space:]]*$")) { in_section=1; next }
    }
    in_section { print }
  ' "$plan_path"
}

inventory_section="$(extract_section "Slice inventory")"
testing_section="$(extract_section "Testing plan cross-walk")"
metadata_section="$(extract_section "Per-slice planning metadata")"

required_slice_ids=(
  "repo-monorepo-bootstrap"
  "docker-compose-db"
  "mvp-completion-ready"
)

for slice_id in "${required_slice_ids[@]}"; do
  if ! grep -q "$slice_id" "$plan_path"; then
    FAILURES+=("plan must mention slice id: ${slice_id}")
  fi
done

if [[ -n "$inventory_section" ]]; then
  if ! grep -Eiq 'phase[[:space:]]*0|infra' <<< "$inventory_section"; then
    FAILURES+=("Slice inventory must describe phase 0 infra slices")
  fi
  if ! grep -Eiq 'mvp-completion-ready|phase[[:space:]]*4' <<< "$inventory_section"; then
    FAILURES+=("Slice inventory must describe mvp-completion-ready finale slice")
  fi
else
  FAILURES+=("Slice inventory section is empty")
fi

if [[ -n "$testing_section" ]]; then
  if ! grep -qF '11-testing-plan.md' <<< "$testing_section" && ! grep -qE '§[0-9]' <<< "$testing_section"; then
    FAILURES+=("Testing plan cross-walk must reference testing-plan sections (§) or docs/technical/11-testing-plan.md")
  fi
else
  FAILURES+=("Testing plan cross-walk section is empty")
fi

if [[ -n "$metadata_section" ]]; then
  if ! grep -Eiq 'requiresPlan' <<< "$metadata_section"; then
    FAILURES+=("Per-slice planning metadata must mention requiresPlan for infra vs non-infra slices")
  fi
  if ! grep -Eiq 'testingPlanRefs' <<< "$metadata_section"; then
    FAILURES+=("Per-slice planning metadata must propose testingPlanRefs for non-infra slices")
  fi
else
  FAILURES+=("Per-slice planning metadata section is empty")
fi

ac_file="$(resolve_repo_path docs/brds/08-acceptance-mvp-future.md)"
if [[ -f "$ac_file" ]]; then
  ac_count=0
  ac_missing=0
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    ac_count=$((ac_count + 1))
    if ! grep -q "$tag" "$plan_path"; then
      ac_missing=$((ac_missing + 1))
    fi
  done < <(grep -oE 'AC-[0-9]{2}' "$ac_file" 2>/dev/null | sort -u | head -20)
  if [[ "$ac_count" -gt 0 && "$ac_missing" -gt "$((ac_count / 2))" ]]; then
    FAILURES+=("too many AC tags from acceptance doc missing from plan (${ac_missing}/${ac_count} sampled)")
  fi
fi

module_file="$(resolve_repo_path docs/technical/02-module-breakdown.md)"
if [[ -f "$module_file" ]]; then
  module_hits=0
  while IFS= read -r slug; do
    [[ -z "$slug" ]] && continue
    if grep -q "module-${slug}" "$plan_path" || grep -qi "$slug" "$plan_path"; then
      module_hits=$((module_hits + 1))
    fi
  done < <(grep -oE '##[[:space:]]+[A-Za-z0-9][A-Za-z0-9 -]*' "$module_file" 2>/dev/null | sed 's/^##[[:space:]]*//' | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | head -15)
  if [[ "$module_hits" -lt 1 ]]; then
    FAILURES+=("plan should reference modules from 02-module-breakdown.md")
  fi
fi

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  log_err "harness-backlog plan validation failed:"
  printf '%s\n' "${FAILURES[@]}" >&2
  exit 1
fi

log_ok "harness-backlog plan validation passed"
exit 0
