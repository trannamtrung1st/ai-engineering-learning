#!/usr/bin/env bash
# Resolve doc paths for a ManualsGen backlog item from manualsgen-docs-map + context-map + item sourceDocs
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${_LIB_DIR}/common.sh"

resolve_docs_for_manual_item() {
  local item_id="$1"
  local item_type
  item_type="$(manual_item_type "$item_id")"

  {
    jq -r --arg t "$item_type" '
      (.alwaysRead // []) as $always |
      ([.typeRules[]? | select(.type == $t) | .docs[]?] // []) as $typeDocs |
      ($always + $typeDocs) | unique | .[]
    ' "$MANUALSGEN_DOCS_MAP" 2>/dev/null || true
    jq -r '.agents.manualsgen.alwaysRead[]?' "$CONTEXT_MAP" 2>/dev/null || true
    get_manual_item_json "$item_id" | jq -r '.sourceDocs[]?' 2>/dev/null || true
  } | sort -u
}

resolve_docs_list_for_manual_item() {
  local item_id="$1"
  resolve_docs_for_manual_item "$item_id" | sort -u
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  require_harness_deps
  ITEM_ID="${1:?manual item id required}"
  resolve_docs_list_for_manual_item "$ITEM_ID" | sed 's/^/- /'
fi
