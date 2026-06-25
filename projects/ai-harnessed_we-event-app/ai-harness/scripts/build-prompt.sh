#!/usr/bin/env bash
# Build implementer or reviewer prompt for a slice
# Usage: build-prompt.sh <sliceId> [implementer|reviewer]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

SLICE_ID="${1:?slice id required}"
MODE="${2:-implementer}"

if [[ "$MODE" != "implementer" && "$MODE" != "reviewer" ]]; then
  echo "ERROR: mode must be implementer or reviewer" >&2
  exit 1
fi

slice_json="$(get_slice_json "$SLICE_ID")"
if [[ -z "$slice_json" || "$slice_json" == "null" ]]; then
  echo "ERROR: slice not found: $SLICE_ID" >&2
  exit 1
fi

description="$(echo "$slice_json" | jq -r '.description // ""')"
acceptance="$(echo "$slice_json" | jq -r '.acceptance | join(", ")')"
artifacts="$(echo "$slice_json" | jq -r '.completionArtifacts | join(", ")')"
agent_type="$(echo "$slice_json" | jq -r '.agent // "backend"')"

# Merge slice docs with agent alwaysRead from context-map
docs_list="$(jq -r --arg id "$SLICE_ID" --arg agent "$agent_type" '
  .slices[$id].docs // [] as $sliceDocs |
  .agents[$agent].alwaysRead // [] as $always |
  ($always + $sliceDocs) | unique | .[] | "- " + .
' "$CONTEXT_MAP" 2>/dev/null || echo "$slice_json" | jq -r '.docs[]? | "- " + .')"

if [[ -z "$docs_list" ]]; then
  docs_list="$(echo "$slice_json" | jq -r '.docs[]? | "- " + .')"
fi

template_file="${HARNESS_ROOT}/agents/${MODE}.prompt.md"
if [[ ! -f "$template_file" ]]; then
  echo "ERROR: template not found: $template_file" >&2
  exit 1
fi

prompt="$(cat "$template_file")"
prompt="${prompt//\{\{SLICE_ID\}\}/$SLICE_ID}"
prompt="${prompt//\{\{SLICE_DESCRIPTION\}\}/$description}"
prompt="${prompt//\{\{SLICE_ACCEPTANCE\}\}/$acceptance}"
prompt="${prompt//\{\{SLICE_ARTIFACTS\}\}/$artifacts}"
prompt="${prompt//\{\{SLICE_AGENT\}\}/$agent_type}"
prompt="${prompt//\{\{SLICE_DOCS\}\}/$docs_list}"

printf '%s\n' "$prompt"
