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

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  require_harness_deps
  TAG="${1:?requirement tag required}"
  resolve_docs_list_for_requirement_tag "$TAG" | sed 's/^/- /'
fi
