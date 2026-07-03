#!/usr/bin/env bash
# Compute doc fingerprint for a slice or requirement tag
# Usage: doc-fingerprint.sh <id> [--requirement-tag]
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${_LIB_DIR}/common.sh"
# shellcheck source=resolve-testgen-docs.sh
source "${_LIB_DIR}/resolve-testgen-docs.sh"

_fingerprint_from_paths() {
  local doc_lines="$1"
  local -a paths=()
  local path
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    paths+=("$path")
  done <<< "$doc_lines"

  if [[ ${#paths[@]} -eq 0 ]]; then
    echo "ERROR: no docs provided" >&2
    return 1
  fi

  local sorted hash_input=""
  sorted="$(printf '%s\n' "${paths[@]}" | sort -u)"
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    if [[ ! -f "$REPO_ROOT/$path" ]]; then
      echo "WARN: missing doc: $path" >&2
      hash_input+="${path}:MISSING"$'\n'
      continue
    fi
    hash_input+="${path}:"$'\n'
    hash_input+="$(cat "$REPO_ROOT/$path")"$'\n'
  done <<< "$sorted"

  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$hash_input" | shasum -a 256 | awk '{print "sha256:" $1}'
  else
    printf '%s' "$hash_input" | sha256sum | awk '{print "sha256:" $1}'
  fi
}

compute_requirement_tag_doc_fingerprint() {
  local requirement_tag="$1"
  local doc_lines
  doc_lines="$(resolve_docs_list_for_requirement_tag "$requirement_tag")"
  _fingerprint_from_paths "$doc_lines"
}

compute_product_item_doc_fingerprint() {
  compute_requirement_tag_doc_fingerprint "$@"
}

compute_slice_doc_fingerprint() {
  local slice_id="$1"
  local agent_type
  agent_type="$(get_slice_field "$slice_id" agent)"

  local doc_lines
  doc_lines="$(jq -r --arg id "$slice_id" --arg agent "$agent_type" '
    (.slices[$id].docs // []) as $sliceDocs |
    (.agents[$agent].alwaysRead // []) as $always |
    ($always + $sliceDocs) | unique | .[]
  ' "$CONTEXT_MAP" 2>/dev/null || true)"

  if [[ -z "$doc_lines" ]]; then
    doc_lines="$(get_slice_json "$slice_id" | jq -r '.docs[]?')"
  fi

  _fingerprint_from_paths "$doc_lines"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  require_harness_deps
  ID="${1:?id required}"
  if [[ "${2:-}" == "--requirement-tag" || "${2:-}" == "--product-item" ]]; then
    compute_requirement_tag_doc_fingerprint "$ID"
  else
    compute_slice_doc_fingerprint "$ID"
  fi
fi
