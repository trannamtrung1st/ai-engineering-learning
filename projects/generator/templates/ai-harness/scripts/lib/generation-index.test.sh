#!/usr/bin/env bash
# Regression: generation index jq helpers collapse duplicated JSON objects.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

mkdir -p "$FIXTURE/ai-harness/scripts/lib" "$FIXTURE/ai-harness/state" "$FIXTURE/ai-harness/generated/runs"
mkdir -p "$FIXTURE/ai-harness/workflows" "$FIXTURE/ai-harness/config"
mkdir -p "$FIXTURE/docs/test-cases/items"
cp -R "$ROOT/scripts/"* "$FIXTURE/ai-harness/scripts/"

cat > "$FIXTURE/ai-harness/whole-app-backlog.json" <<'EOF'
{
  "branchName": "aih/test-mvp",
  "slices": [
    {
      "id": "module-auth",
      "passes": false,
      "priority": 1,
      "phase": 1,
      "agent": "backend",
      "acceptance": ["FR-01"],
      "docs": [],
      "description": "auth"
    }
  ]
}
EOF

cat > "$FIXTURE/ai-harness/test-case-index.json" <<'EOF'
{
  "current": [],
  "docFingerprint": null,
  "tags": {
    "FR-01": { "current": false, "docFingerprint": "old", "generatedAt": null }
  }
}
{
  "current": [],
  "docFingerprint": null,
  "tags": {
    "FR-01": { "current": false, "docFingerprint": "old", "generatedAt": null }
  }
}
EOF

cp "$ROOT/workflows/testgen-loop.json" "$FIXTURE/ai-harness/workflows/"
cp "$ROOT/config/testgen-docs-map.json" "$FIXTURE/ai-harness/config/"

cd "$FIXTURE"
# shellcheck disable=SC1091
source "$FIXTURE/ai-harness/scripts/lib/common.sh"

if requirement_tag_test_cases_current "FR-01"; then
  echo "FAIL: duplicate index should not read as current" >&2
  exit 1
fi

mark_test_cases_current "FR-01" "fp-new"

object_count="$(jq -s 'length' "$TEST_CASE_INDEX")"
if [[ "$object_count" -ne 1 ]]; then
  echo "FAIL: expected 1 JSON object after mark_test_cases_current, got ${object_count}" >&2
  exit 1
fi

if ! jq empty "$TEST_CASE_INDEX" 2>/dev/null; then
  echo "FAIL: test-case-index.json is not strict-valid JSON" >&2
  exit 1
fi

if ! requirement_tag_test_cases_current "FR-01"; then
  echo "FAIL: FR-01 should be current after mark" >&2
  exit 1
fi

stored_fp="$(jq_generation_index_read "$TEST_CASE_INDEX" --arg id "FR-01" '.[0] | .tags[$id].docFingerprint // ""')"
if [[ "$stored_fp" != "fp-new" ]]; then
  echo "FAIL: expected docFingerprint fp-new, got ${stored_fp}" >&2
  exit 1
fi

stale_lines="$(list_stale_requirement_tags | wc -l | tr -d ' ')"
if [[ "$stale_lines" -ne 0 ]]; then
  echo "FAIL: expected no stale tags, got ${stale_lines} lines" >&2
  exit 1
fi

echo "generation-index.test.sh: ok"
