#!/usr/bin/env bash
# Validate generated user manual markdown for a backlog item
# Usage: validate-user-manuals.sh <manualItemId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

ITEM_ID="${1:?manual item id required}"
ARTIFACT="$(manual_artifact_abs "$ITEM_ID")"
item_json="$(get_manual_item_json "$ITEM_ID")"

if [[ -z "$item_json" || "$item_json" == "null" ]]; then
  echo "ERROR: manual item not found: $ITEM_ID" >&2
  exit 1
fi

ITEM_TYPE="$(echo "$item_json" | jq -r '.type // ""')"
OUTPUT_PATH="$(echo "$item_json" | jq -r '.outputPath // ""')"

PASS=true
FAILURES=()

if [[ ! -f "$ARTIFACT" ]]; then
  echo "ERROR: manual artifact not found: $ARTIFACT" >&2
  exit 1
fi

prefix="$(jq -r '.validation.outputPathPrefix // "docs/user-manuals/"' "$MANUALSGEN_CONFIG")"
if [[ "$OUTPUT_PATH" != ${prefix}* ]]; then
  FAILURES+=("outputPath must start with ${prefix}")
  PASS=false
fi

if [[ "$ITEM_TYPE" == "flow" ]]; then
  flow_pattern="$(jq -r '.validation.flowIdPattern // "^FLOW-[0-9]{2}$"' "$MANUALSGEN_CONFIG")"
  if [[ ! "$ITEM_ID" =~ $flow_pattern ]]; then
    FAILURES+=("flow item id must match ${flow_pattern}: ${ITEM_ID}")
    PASS=false
  fi
fi

min_lines="$(jq -r --arg t "$ITEM_TYPE" '.validation.minLines[$t] // 20' "$MANUALSGEN_CONFIG")"
line_count="$(wc -l < "$ARTIFACT" | tr -d ' ')"
if [[ "$line_count" -lt "$min_lines" ]]; then
  FAILURES+=("artifact has ${line_count} lines; minimum ${min_lines} for type ${ITEM_TYPE}")
  PASS=false
fi

if ! head -1 "$ARTIFACT" | grep -q '^---$'; then
  FAILURES+=("missing YAML frontmatter opening ---")
  PASS=false
fi

if ! grep -q '^docFingerprint:' "$ARTIFACT"; then
  FAILURES+=("frontmatter missing docFingerprint")
  PASS=false
fi

if grep -qiE 'generator/|Lorem ipsum|demo-item' "$ARTIFACT"; then
  FAILURES+=("forbidden placeholder or generator reference in artifact")
  PASS=false
fi

while IFS= read -r heading; do
  [[ -z "$heading" ]] && continue
  if ! grep -qiE "^#+ .*${heading}" "$ARTIFACT"; then
    FAILURES+=("missing required heading: ${heading}")
    PASS=false
  fi
done < <(jq -r --arg t "$ITEM_TYPE" '.validation.requiredHeadings[$t][]?' "$MANUALSGEN_CONFIG" 2>/dev/null)

if [[ "$ITEM_TYPE" == "runbook" ]]; then
  while IFS= read -r flow_id; do
    [[ -z "$flow_id" ]] && continue
    flow_path="$(manual_artifact_path "$flow_id")"
    if [[ -f "${REPO_ROOT}/${flow_path}" ]] && ! grep -q "$flow_id" "$ARTIFACT"; then
      FAILURES+=("runbook must reference flow ${flow_id}")
      PASS=false
    fi
  done < <(jq -r '.items[] | select(.type == "flow") | .id' "$MANUALS_BACKLOG" 2>/dev/null)
fi

if [[ "$PASS" != true ]]; then
  echo "Manual validation failed for ${ITEM_ID}:" >&2
  for msg in "${FAILURES[@]}"; do
    echo "  - ${msg}" >&2
  done
  exit 1
fi

echo "Manual validation passed for ${ITEM_ID}"
exit 0
