#!/usr/bin/env bash
# Compare live harness vs generator templates and classify deltas for backport.
# Usage: backport-harness-diff.sh [live-harness-dir]
#
# Env:
#   GEN_LIVE_HARNESS — override live harness path (default: auto-detect sibling ai-harnessed_*/ai-harness)
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

LIVE="${1:-${GEN_LIVE_HARNESS:-}}"
TEMPLATE="${TEMPLATES_DIR}/ai-harness"

if [[ -z "$LIVE" ]]; then
  for candidate in "${GEN_ROOT}"/../*/ai-harness; do
    [[ -d "$candidate/scripts" ]] || continue
    LIVE="$candidate"
    break
  done
fi

if [[ -z "$LIVE" || ! -d "$LIVE" ]]; then
  gen_err "live harness not found — pass path or set GEN_LIVE_HARNESS"
  exit 1
fi

if [[ ! -d "$TEMPLATE" ]]; then
  gen_err "templates missing: $TEMPLATE"
  exit 1
fi

SKIP_PATTERNS=(
  'whole-app-backlog.json'
  'test-case-index.json'
  'plans/whole-app-backlog.md'
  'plans/'
  'manuals-backlog.json'
  'manuals-index.json'
  'playwright-regression-index.json'
  'state/progress.md'
  'state/guardrails.md'
  'generated/'
  'mvp-integration-'
  'context-map.json'
  'testgen-docs-map.json'
  'manualsgen-docs-map.json'
)

should_skip() {
  local rel="$1"
  local pat
  for pat in "${SKIP_PATTERNS[@]}"; do
    [[ "$rel" == *"$pat"* ]] && return 0
  done
  return 1
}

is_placeholder_delta() {
  local live_file="$1"
  local rel="$2"
  # Product literals that should become placeholders in templates
  if grep -qE 'Attendly|@attendly/|attendly-test|attendly\.local' "$live_file" 2>/dev/null; then
    return 0
  fi
  if [[ "$rel" == *".prompt.md" ]] && grep -q '{{PRODUCT_NAME}}' "${TEMPLATE}/${rel}" 2>/dev/null; then
    if ! grep -q '{{PRODUCT_NAME}}' "$live_file" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

gen_step "Backport diff: ${LIVE} → ${TEMPLATE}"

port=()
placeholder=()
skipped=()
only_live=()

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if [[ "$line" == Only\ in* ]]; then
    dir="${line#Only in }"
    dir="${dir%%: *}"
    file="${line#*: }"
    if [[ "$dir" == "$LIVE"* || "$dir" == "$LIVE" ]]; then
      rel="${file}"
      if should_skip "$rel"; then
        skipped+=("$rel (only in live)")
      else
        only_live+=("$rel")
      fi
    elif [[ "$dir" == "$TEMPLATE"* || "$dir" == "$TEMPLATE" ]]; then
      skipped+=("$file (only in template)")
    fi
    continue
  fi
  if [[ "$line" != Files* ]]; then
    continue
  fi
  live_file="${line#Files }"
  live_file="${live_file%% and *}"
  rel="${live_file#${LIVE}/}"
  tpl_file="${TEMPLATE}/${rel}"

  if should_skip "$rel"; then
    skipped+=("$rel")
    continue
  fi

  if [[ ! -f "$tpl_file" ]]; then
    port+=("$rel (new in live)")
    continue
  fi

  if is_placeholder_delta "$live_file" "$rel"; then
    placeholder+=("$rel")
  else
    port+=("$rel")
  fi
done < <(diff -rq "$LIVE" "$TEMPLATE" 2>/dev/null || true)

echo ""
echo "=== PORT (generic — copy to templates) ==="
if [[ "${#port[@]}" -eq 0 ]]; then
  echo "(none)"
else
  printf '  %s\n' "${port[@]}"
fi

echo ""
echo "=== PLACEHOLDER (generalize before porting) ==="
if [[ "${#placeholder[@]}" -eq 0 ]]; then
  echo "(none)"
else
  printf '  %s\n' "${placeholder[@]}"
fi

echo ""
echo "=== ONLY IN LIVE (review — may be product-specific) ==="
if [[ "${#only_live[@]}" -eq 0 ]]; then
  echo "(none)"
else
  printf '  %s\n' "${only_live[@]}"
fi

echo ""
echo "=== SKIP (runtime / product maps) ==="
echo "  ${#skipped[@]} paths skipped"

if [[ "${#port[@]}" -gt 0 ]]; then
  exit 1
fi
exit 0
