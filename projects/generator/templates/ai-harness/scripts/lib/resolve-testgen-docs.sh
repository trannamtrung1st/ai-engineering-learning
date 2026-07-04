#!/usr/bin/env bash
# Resolve doc paths for a requirement tag (AC/FR/BR/NFR) from testgen-docs-map + context-map
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${_LIB_DIR}/common.sh"

resolve_docs_for_requirement_tag() {
  local tag="$1"
  local prefix="${tag%%-*}"

  {
    jq -r --arg tag "$tag" --arg prefix "$prefix" '
      (.alwaysRead // []) as $always |
      ([.rules[]? as $r | select($tag | test($r.match)) | $r.docs[]?] // []) as $ruleDocs |
      (.prefixDefaults[$prefix] // []) as $prefixDocs |
      ($always + $ruleDocs + $prefixDocs) | unique | .[]
    ' "$TESTGEN_DOCS_MAP" 2>/dev/null || true
    jq -r '.agents.testgen.alwaysRead[]?' "$CONTEXT_MAP" 2>/dev/null || true
  } | sort -u
}

resolve_docs_list_for_requirement_tag() {
  local tag="$1"
  resolve_docs_for_requirement_tag "$tag" | sort -u
}

resolve_coverage_hints_for_requirement_tag() {
  local tag="$1"
  jq -r --arg tag "$tag" '
    [.rules[]? as $r | select($tag | test($r.match)) | $r.coverageHints[]?] | unique | .[]
  ' "$TESTGEN_DOCS_MAP" 2>/dev/null || true
}

format_coverage_hints_block() {
  local tag="$1"
  local hints
  hints="$(resolve_coverage_hints_for_requirement_tag "$tag")"
  if [[ -z "$hints" ]]; then
    echo ""
    return 0
  fi
  echo "## Tag-specific coverage hints"
  echo ""
  while IFS= read -r hint; do
    [[ -z "$hint" ]] && continue
    echo "- ${hint}"
  done <<< "$hints"
}

format_layer_policy_block() {
  local tag="$1"
  local policy_json
  policy_json="$(jq -c --arg tag "$tag" '
    . as $cfg |
    reduce (($cfg.validation.layerPolicy // {}) | to_entries[]) as $e (
      null;
      if ($tag | test("^" + ($e.key | gsub("\\*"; ".*")) + "$")) then $e.value else . end
    )
  ' "$TESTGEN_CONFIG" 2>/dev/null)"

  if [[ -z "$policy_json" || "$policy_json" == "null" ]]; then
    echo ""
    return 0
  fi

  local required_layers min_integration min_e2e
  required_layers="$(echo "$policy_json" | jq -r '.requiredLayers // [] | join(", ")')"
  min_integration="$(echo "$policy_json" | jq -r '.minPerLayer.integration // 0')"
  min_e2e="$(echo "$policy_json" | jq -r '.minPerLayer.e2e // 0')"

  local category_policy_json
  category_policy_json="$(jq -c --arg tag "$tag" '
    . as $cfg |
    reduce (($cfg.validation.categoryPolicy // {}) | to_entries[]) as $e (
      null;
      if ($tag | test("^" + ($e.key | gsub("\\*"; ".*")) + "$")) then $e.value else . end
    )
  ' "$TESTGEN_CONFIG" 2>/dev/null)"

  echo "## Layer policy for this tag"
  echo ""
  echo "Harness validation requires:"
  [[ -n "$required_layers" ]] && echo "- Layers: ${required_layers}"
  [[ "$min_integration" != "0" ]] && echo "- At least ${min_integration} integration case(s)"
  [[ "$min_e2e" != "0" ]] && echo "- At least ${min_e2e} e2e case(s)"

  if [[ -n "$category_policy_json" && "$category_policy_json" != "null" ]]; then
    local functional_min
    functional_min="$(echo "$category_policy_json" | jq -r '.minCasesPerCategory.functional // empty')"
    if [[ -n "$functional_min" ]]; then
      echo "- Category: functional minimum **${functional_min}** (NFR tag — use \`non-functional\` for constraint cases)"
    fi
  fi

  if jq -e --arg tag "$tag" '
    (.validation.browserRequiredWhen.tagMatches // [])[] as $p
    | select($tag | test($p))
  ' "$TESTGEN_CONFIG" >/dev/null 2>&1; then
    local min_browser
    min_browser="$(jq -r '.validation.browserRequiredWhen.minBrowserCases // 1' "$TESTGEN_CONFIG")"
    echo "- At least ${min_browser} browser case(s) (UI-facing tag)"
  fi

  local uiux_docs_include
  uiux_docs_include="$(jq -r '.validation.uiUxRequiredWhen.docsInclude // empty' "$TESTGEN_CONFIG" 2>/dev/null || true)"
  if [[ -n "$uiux_docs_include" ]]; then
    local resolved_uiux
    resolved_uiux="$(resolve_docs_for_requirement_tag "$tag" | tr '\n' ' ')"
    if [[ "$resolved_uiux" == *"$uiux_docs_include"* ]]; then
      local min_uiux
      min_uiux="$(jq -r '.validation.uiUxRequiredWhen.minUiUxCases // 1' "$TESTGEN_CONFIG")"
      echo "- At least ${min_uiux} ui-ux case(s) (category \`ui-ux\`, a \`ui-*\` technique — UI-facing tag per ${uiux_docs_include})"
    fi
  fi

  local allowed_layers
  allowed_layers="$(jq -r '.validation.allowedLayers // ["integration", "e2e", "browser"] | join(", ")' "$TESTGEN_CONFIG")"
  echo ""
  echo "Allowed layers for this artifact: ${allowed_layers}. Do **not** emit unit-layer cases — unit tests are the implementer's responsibility."
}

testgen_tag_matches_pattern() {
  local tag="$1"
  local pattern="$2"
  [[ "$tag" =~ $pattern ]]
}

format_technique_requirements_block() {
  local tag="$1"
  local docs_list technique tag_pattern docs_include rule
  local -a lines=()

  docs_list="$(resolve_docs_for_requirement_tag "$tag" | tr '\n' ' ')"

  while IFS= read -r technique; do
    [[ -z "$technique" ]] && continue
    lines+=("- \`${technique}\` (required by \`techniquePolicy\`)")
  done < <(jq -r --arg tag "$tag" '
    reduce ((.validation.techniquePolicy // {}) | to_entries[]) as $e (
      [];
      if ($tag | test("^" + ($e.key | gsub("\\*"; ".*")) + "$")) then . + $e.value else . end
    ) | unique | .[]
  ' "$TESTGEN_CONFIG" 2>/dev/null)

  while IFS= read -r rule; do
    [[ -z "$rule" ]] && continue
    tag_pattern="$(echo "$rule" | jq -r '.tagMatches')"
    docs_include="$(echo "$rule" | jq -r '.docsInclude // empty')"
    if ! testgen_tag_matches_pattern "$tag" "$tag_pattern"; then
      continue
    fi
    if [[ -n "$docs_include" && "$docs_list" != *"$docs_include"* ]]; then
      continue
    fi
    while IFS= read -r technique; do
      [[ -z "$technique" ]] && continue
      lines+=("- \`${technique}\` (required by \`techniqueWhen\` rule: \`${tag_pattern}\`)")
    done < <(echo "$rule" | jq -r '.require[]?')
  done < <(jq -c '.validation.techniqueWhen[]?' "$TESTGEN_CONFIG" 2>/dev/null)

  if [[ "${#lines[@]}" -eq 0 ]]; then
    echo ""
    return 0
  fi

  echo "## Harness technique requirements for this tag"
  echo ""
  echo "Validation fails unless the artifact includes **at least one case** per technique below (set \`technique\` on each case):"
  echo ""
  printf '%s\n' "${lines[@]}"
  echo ""
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  require_harness_deps
  TAG="${1:?requirement tag required}"
  resolve_docs_list_for_requirement_tag "$TAG" | sed 's/^/- /'
fi
