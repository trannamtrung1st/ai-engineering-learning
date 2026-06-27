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

  echo "## Layer policy for this tag"
  echo ""
  echo "Harness validation requires:"
  [[ -n "$required_layers" ]] && echo "- Layers: ${required_layers}"
  [[ "$min_integration" != "0" ]] && echo "- At least ${min_integration} integration case(s)"
  [[ "$min_e2e" != "0" ]] && echo "- At least ${min_e2e} e2e case(s)"

  if jq -e --arg tag "$tag" '
    (.validation.browserRequiredWhen.tagMatches // [])[]
    | select($tag | test(.))
  ' "$TESTGEN_CONFIG" >/dev/null 2>&1; then
    local min_browser
    min_browser="$(jq -r '.validation.browserRequiredWhen.minBrowserCases // 1' "$TESTGEN_CONFIG")"
    echo "- At least ${min_browser} browser case(s) (UI-facing tag)"
  fi

  local allowed_layers
  allowed_layers="$(jq -r '.validation.allowedLayers // ["integration", "e2e", "browser"] | join(", ")' "$TESTGEN_CONFIG")"
  echo ""
  echo "Allowed layers for this artifact: ${allowed_layers}. Do **not** emit unit-layer cases — unit tests are the implementer's responsibility."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  require_harness_deps
  TAG="${1:?requirement tag required}"
  resolve_docs_list_for_requirement_tag "$TAG" | sed 's/^/- /'
fi
