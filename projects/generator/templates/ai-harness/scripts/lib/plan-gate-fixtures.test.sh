#!/usr/bin/env bash
# Fixture tests for slice plan gate validators (macOS bash + BSD awk compatible)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
HARNESS_TPL="$ROOT"
FIXTURE="$(mktemp -d)"
fail=0

cleanup() { rm -rf "$FIXTURE"; }
trap cleanup EXIT

setup_fixture_repo() {
  mkdir -p "$FIXTURE/ai-harness/scripts/lib" "$FIXTURE/ai-harness/workflows" "$FIXTURE/ai-harness/config"
  mkdir -p "$FIXTURE/ai-harness/state" "$FIXTURE/ai-harness/plans" "$FIXTURE/ai-harness/generated/runs"
  mkdir -p "$FIXTURE/docs/technical"
  cp -R "$HARNESS_TPL/scripts/"* "$FIXTURE/ai-harness/scripts/"
  cp "$HARNESS_TPL/workflows/ralph-loop.json" "$FIXTURE/ai-harness/workflows/"
  cp "$HARNESS_TPL/config/context-map.json" "$FIXTURE/ai-harness/config/"
  cp "$HARNESS_TPL/config/plan-index.json" "$FIXTURE/ai-harness/config/" 2>/dev/null || \
    echo '{"current":[],"docFingerprint":null,"tags":{}}' > "$FIXTURE/ai-harness/config/plan-index.json"
  chmod +x "$FIXTURE/ai-harness/scripts/"*.sh
  for f in 11-testing-plan 00-system-overview 08-validation-rules 12-backend-frontend-tech-stack; do
    echo "# stub" > "$FIXTURE/docs/technical/${f}.md"
  done
}

assert_ok() {
  local label="$1"
  shift
  if "$@"; then
    echo "ok: $label"
  else
    echo "FAIL: $label" >&2
    fail=1
  fi
}

assert_fail() {
  local label="$1"
  shift
  if "$@"; then
    echo "FAIL (expected error): $label" >&2
    fail=1
  else
    echo "ok: $label (expected failure)"
  fi
}

setup_fixture_repo

# --- validate-slice-plan: good plan ---
cat > "$FIXTURE/ai-harness/whole-app-backlog.json" <<'EOF'
{"branchName":"aih/test-mvp","slices":[{"id":"module-foo","passes":false,"priority":20,"phase":1,"agent":"backend","acceptance":["AC-01"],"docs":["docs/technical/11-testing-plan.md"],"description":"test","completionArtifacts":["apps/api/foo.ts"],"testingPlanRefs":["§3.2"],"requiresPlan":true}]}
EOF
cat > "$FIXTURE/ai-harness/plans/module-foo.md" <<'EOF'
# Plan: module-foo
## Acceptance coverage
- AC-01: foo
## Testing plan alignment
- §3.2
## Files to create or modify
- apps/api/foo.ts
## Test strategy
- integration: apps/api/foo.integration.test.ts
## Implementation sequence
1. step
## Risks and deferrals
- none
EOF
(
  cd "$FIXTURE"
  assert_ok "validate-slice-plan passes good plan" ./ai-harness/scripts/validate-slice-plan.sh module-foo
)

# --- validate-slice-plan: empty test strategy fails ---
cat > "$FIXTURE/ai-harness/plans/module-foo.md" <<'EOF'
# Plan: module-foo
## Acceptance coverage
- AC-01: foo
## Testing plan alignment
- §3.2
## Files to create or modify
- apps/api/foo.ts
## Test strategy

## Implementation sequence
1. step
## Risks and deferrals
- none
EOF
(
  cd "$FIXTURE"
  assert_fail "validate-slice-plan rejects empty test strategy" ./ai-harness/scripts/validate-slice-plan.sh module-foo
)

# --- validate-backlog: legacy without requiresPlan passes ---
cat > "$FIXTURE/ai-harness/whole-app-backlog.json" <<'EOF'
{"branchName":"aih/test","slices":[{"id":"module-foo","passes":false,"priority":20,"phase":1,"agent":"backend","acceptance":["AC-01"],"docs":["docs/technical/02-module-breakdown.md"],"description":"test","completionArtifacts":["apps/api/foo.ts"]}]}
EOF
(
  cd "$FIXTURE"
  assert_ok "validate-backlog passes legacy slice without requiresPlan" ./ai-harness/scripts/validate-backlog.sh --quiet
)

# --- validate-backlog: explicit requiresPlan without testingPlanRefs fails ---
cat > "$FIXTURE/ai-harness/whole-app-backlog.json" <<'EOF'
{"branchName":"aih/test","slices":[{"id":"module-foo","passes":false,"priority":20,"phase":1,"agent":"backend","acceptance":["AC-01"],"docs":["docs/technical/11-testing-plan.md"],"description":"test","completionArtifacts":["apps/api/foo.ts"],"requiresPlan":true}]}
EOF
(
  cd "$FIXTURE"
  assert_fail "validate-backlog fails when requiresPlan:true but no testingPlanRefs" ./ai-harness/scripts/validate-backlog.sh --quiet
)

# --- slice_requires_plan: legacy skips when requireExplicitRequiresPlan true ---
cat > "$FIXTURE/ai-harness/whole-app-backlog.json" <<'EOF'
{"branchName":"aih/test","slices":[{"id":"module-foo","passes":false,"priority":20,"phase":1,"agent":"backend","acceptance":["AC-01"],"docs":["docs/technical/02-module-breakdown.md"],"description":"test","completionArtifacts":["apps/api/foo.ts"]}]}
EOF
cd "$FIXTURE"
# shellcheck source=/dev/null
source ./ai-harness/scripts/lib/common.sh
if slice_requires_plan module-foo; then
  echo "FAIL: legacy slice should skip plan when requireExplicitRequiresPlan=true" >&2
  fail=1
else
  echo "ok: slice_requires_plan skips legacy backlog"
fi
cd - >/dev/null

# --- generator harness-backlog-plan validator ---
GEN_PLAN="$FIXTURE/ai-harness/plans/whole-app-backlog.md"
cat > "$GEN_PLAN" <<'EOF'
# Plan: whole-app-backlog
## Product scope and branch
branch aih/test-mvp
## Slice inventory
- repo-monorepo-bootstrap phase 0 infra
- docker-compose-db phase 0 infra
- module-foo phase 1 backend
- mvp-completion-ready phase 4 finale
## Acceptance tag mapping
- AC-01 -> module-foo
## Testing plan cross-walk
- docs/technical/11-testing-plan.md §3.2 integration
## Per-slice planning metadata
- module-foo requiresPlan: true testingPlanRefs: ["§3.2"]
- repo-monorepo-bootstrap requiresPlan: false
## Risks and open questions
- none
EOF
(
  GEN_REPO_ROOT="$FIXTURE" "$GEN_ROOT/scripts/validate-harness-backlog-plan.sh"
  echo "ok: validate-harness-backlog-plan passes fixture"
)

if [[ "$fail" -ne 0 ]]; then
  echo "plan-gate-fixtures.test.sh FAILED" >&2
  exit 1
fi
echo "plan-gate-fixtures.test.sh passed"
exit 0
