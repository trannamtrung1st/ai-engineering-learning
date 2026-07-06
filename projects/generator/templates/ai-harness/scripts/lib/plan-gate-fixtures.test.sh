#!/usr/bin/env bash
# Fixture tests for work plan gate validators (macOS bash + BSD awk compatible)
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

# --- validate-work-plan: good plan ---
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
  assert_ok "validate-work-plan passes good plan" ./ai-harness/scripts/validate-work-plan.sh module-foo
)

# --- validate-work-plan: glob completionArtifacts accept concrete filenames ---
cat > "$FIXTURE/ai-harness/whole-app-backlog.json" <<'EOF'
{"branchName":"aih/test-mvp","slices":[{"id":"module-glob","passes":false,"priority":20,"phase":1,"agent":"backend","acceptance":["AC-01"],"docs":["docs/technical/11-testing-plan.md"],"description":"glob artifact slice","completionArtifacts":["apps/api/src/modules/foo/","apps/api/src/modules/foo/*.integration.test.ts"],"testingPlanRefs":["§3.2"],"requiresPlan":true}]}
EOF
cat > "$FIXTURE/ai-harness/plans/module-glob.md" <<'EOF'
# Plan: module-glob
## Acceptance coverage
- AC-01: foo
## Testing plan alignment
- §3.2
## Files to create or modify
- apps/api/src/modules/foo/foo.service.ts — create service
- apps/api/src/modules/foo/foo.integration.test.ts — create integration suite
## Test strategy
- integration: apps/api/src/modules/foo/foo.integration.test.ts
## Implementation sequence
1. step
## Risks and deferrals
- none
EOF
(
  cd "$FIXTURE"
  assert_ok "validate-work-plan accepts concrete file for glob completionArtifact" \
    ./ai-harness/scripts/validate-work-plan.sh module-glob
)

# --- validate-work-plan: prior gate failures require remediation section ---
cat > "$FIXTURE/ai-harness/whole-app-backlog.json" <<'EOF'
{"branchName":"aih/test-mvp","slices":[{"id":"module-retry","passes":false,"priority":20,"phase":1,"agent":"backend","acceptance":["AC-01"],"docs":["docs/technical/11-testing-plan.md"],"description":"retry slice","completionArtifacts":["apps/api/foo.ts"],"testingPlanRefs":["§3.2"],"requiresPlan":true}]}
EOF
cat > "$FIXTURE/ai-harness/generated/runs/run-fail-checks-checks.json" <<'EOF'
{"slice":"module-retry","pass":false,"failures":[{"script":"test:unit","logFile":"ai-harness/generated/runs/run-fail-checks-check-unit.log"}]}
EOF
cat > "$FIXTURE/ai-harness/plans/module-retry.md" <<'EOF'
# Plan: module-retry
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
  assert_fail "validate-work-plan fails without remediation when prior checks failed" \
    ./ai-harness/scripts/validate-work-plan.sh module-retry
)
cat > "$FIXTURE/ai-harness/plans/module-retry.md" <<'EOF'
# Plan: module-retry
## Prior gate failure remediation
- Computational checks (`run-fail-checks`): fix `test:unit` failure in `apps/api/foo.ts`; verify with `npm run aih:run-check -- test:unit`
## Acceptance coverage
- AC-01: foo
## Testing plan alignment
- §3.2
## Files to create or modify
- apps/api/foo.ts
## Test strategy
- integration: apps/api/foo.integration.test.ts
## Implementation sequence
1. Fix `test:unit` per remediation above
2. Continue remaining build steps
## Risks and deferrals
- none
EOF
(
  cd "$FIXTURE"
  assert_ok "validate-work-plan passes with remediation when prior checks failed" \
    ./ai-harness/scripts/validate-work-plan.sh module-retry
)

# Restore module-foo backlog for subsequent fixtures (retry block overwrote it).
cat > "$FIXTURE/ai-harness/whole-app-backlog.json" <<'EOF'
{"branchName":"aih/test-mvp","slices":[{"id":"module-foo","passes":false,"priority":20,"phase":1,"agent":"backend","acceptance":["AC-01"],"docs":["docs/technical/11-testing-plan.md"],"description":"test","completionArtifacts":["apps/api/foo.ts"],"testingPlanRefs":["§3.2"],"requiresPlan":true}]}
EOF

# --- validate-work-plan: TestGen case coverage (implemented + deferred) ---
mkdir -p "$FIXTURE/docs/test-cases/items"
# The coverage loop only runs when the tag's test cases are marked current.
cat > "$FIXTURE/ai-harness/test-case-index.json" <<'EOF'
{"tags":{"AC-01":{"current":true}}}
EOF
cat > "$FIXTURE/docs/test-cases/items/AC-01.json" <<'EOF'
{"requirementTag":"AC-01","cases":[
  {"id":"TC-AC-01-001","layer":"integration"},
  {"id":"TC-AC-01-002","layer":"e2e"},
  {"id":"TC-AC-01-003","layer":"browser"},
  {"id":"TC-AC-01-004","layer":"unit"}
]}
EOF
# Plan implements the integration case and defers the e2e/browser cases.
cat > "$FIXTURE/ai-harness/plans/module-foo.md" <<'EOF'
# Plan: module-foo
## Acceptance coverage
- AC-01: foo
## Testing plan alignment
- §3.2
## Files to create or modify
- apps/api/foo.ts
## Test strategy
- integration: apps/api/foo.integration.test.ts covers TC-AC-01-001
## Implementation sequence
1. step
## Risks and deferrals
- TC-AC-01-002 deferred to module-bar (e2e login flow)
- TC-AC-01-003 deferred to web-shell (browser)
EOF
(
  cd "$FIXTURE"
  assert_ok "validate-work-plan accepts implemented + deferred TestGen cases" ./ai-harness/scripts/validate-work-plan.sh module-foo
)

# --- validate-work-plan: unaccounted TestGen case fails ---
cat > "$FIXTURE/ai-harness/plans/module-foo.md" <<'EOF'
# Plan: module-foo
## Acceptance coverage
- AC-01: foo
## Testing plan alignment
- §3.2
## Files to create or modify
- apps/api/foo.ts
## Test strategy
- integration: apps/api/foo.integration.test.ts covers TC-AC-01-001
## Implementation sequence
1. step
## Risks and deferrals
- TC-AC-01-002 deferred to module-bar (e2e login flow)
EOF
(
  cd "$FIXTURE"
  # TC-AC-01-003 (browser) is neither implemented nor deferred -> must fail.
  assert_fail "validate-work-plan rejects unaccounted TestGen case" ./ai-harness/scripts/validate-work-plan.sh module-foo
)

# Remove the artifact + index so later fixtures keep their original (artifact-free) behavior.
rm -f "$FIXTURE/docs/test-cases/items/AC-01.json" "$FIXTURE/ai-harness/test-case-index.json"

# --- validate-work-plan: empty test strategy fails ---
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
  assert_fail "validate-work-plan rejects empty test strategy" ./ai-harness/scripts/validate-work-plan.sh module-foo
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

# --- planner completion signals exclude PLAN_DONE ---
cd "$FIXTURE"
# shellcheck source=/dev/null
source ./ai-harness/scripts/lib/common.sh
planner_signals="$(agent_work_planner_completion_signals_csv)"
if echo "$planner_signals" | grep -q 'PLAN_DONE'; then
  echo "FAIL: planner signals must not include PLAN_DONE (was: $planner_signals)" >&2
  fail=1
else
  echo "ok: agent_work_planner_completion_signals_csv excludes PLAN_DONE"
fi
if ! echo "$planner_signals" | grep -q 'PLAN_BLOCKED'; then
  echo "FAIL: planner signals should still include PLAN_BLOCKED" >&2
  fail=1
else
  echo "ok: agent_work_planner_completion_signals_csv keeps PLAN_BLOCKED"
fi

# --- wait_for_plan_file polls until file appears ---
AIH_WORK_PLAN_ARTIFACT_WAIT_MS=2000 AIH_WORK_PLAN_ARTIFACT_POLL_MS=100 \
  bash -c '
    cd "'"$FIXTURE"'"
    source ./ai-harness/scripts/lib/common.sh
    plan_path="'"$FIXTURE"'/ai-harness/generated/runs/test-wait-work-plan.md"
    rm -f "$plan_path"
    ( sleep 0.4; echo "# plan" > "$plan_path" ) &
    wait_for_plan_file "$plan_path"
  ' && echo "ok: wait_for_plan_file detects delayed write" || {
  echo "FAIL: wait_for_plan_file should detect delayed write" >&2
  fail=1
}
AIH_WORK_PLAN_ARTIFACT_WAIT_MS=200 AIH_WORK_PLAN_ARTIFACT_POLL_MS=100 \
  bash -c '
    cd "'"$FIXTURE"'"
    source ./ai-harness/scripts/lib/common.sh
    plan_path="'"$FIXTURE"'/ai-harness/generated/runs/test-missing-work-plan.md"
    rm -f "$plan_path"
    ! wait_for_plan_file "$plan_path"
  ' && echo "ok: wait_for_plan_file times out when missing" || {
  echo "FAIL: wait_for_plan_file should time out when file missing" >&2
  fail=1
}

# --- finalize_ephemeral_work_plan validates ephemeral plan ---
cat > "$FIXTURE/ai-harness/whole-app-backlog.json" <<'EOF'
{"branchName":"aih/test","slices":[{"id":"module-fast","passes":false,"priority":20,"phase":1,"agent":"backend","acceptance":["AC-01"],"docs":["docs/technical/11-testing-plan.md"],"description":"test","completionArtifacts":["apps/api/foo.ts"],"testingPlanRefs":["§3.2"],"requiresPlan":true}]}
EOF
cat > "$FIXTURE/docs/test-cases/items/AC-01.json" <<'EOF'
{"requirementTag":"AC-01","cases":[]}
EOF
cat > "$FIXTURE/ai-harness/test-case-index.json" <<'EOF'
{"tags":{"AC-01":{"current":true}}}
EOF
PLAN_EPHEMERAL="$FIXTURE/ai-harness/generated/runs/test-fast-work-plan.md"
cat > "$PLAN_EPHEMERAL" <<'EOF'
# Plan: module-fast
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
  bash -c '
    source ./ai-harness/scripts/lib/common.sh
    require_harness_deps
    if finalize_ephemeral_work_plan module-fast "'"$PLAN_EPHEMERAL"'"; then
      echo "ok: finalize_ephemeral_work_plan validates ephemeral plan"
    else
      echo "FAIL: finalize_ephemeral_work_plan should validate ephemeral plan" >&2
      exit 1
    fi
  '
) || fail=1

# --- wait_for_plan_file_stable detects delayed growth ---
(
  cd "$FIXTURE"
  AIH_WORK_PLAN_ARTIFACT_WAIT_MS=5000 AIH_WORK_PLAN_ARTIFACT_POLL_MS=200 bash -c '
    source ./ai-harness/scripts/lib/common.sh
    require_harness_deps
    artifact="'"$FIXTURE"'/ai-harness/generated/runs/test-stable-work-plan.md"
    printf "# partial\n" > "$artifact"
    (sleep 0.5; cat > "$artifact" <<PLAN
# Plan: module-fast
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
PLAN
    ) &
    if wait_for_plan_file_stable "$artifact"; then
      echo "ok: wait_for_plan_file_stable waits for stable file"
    else
      echo "FAIL: wait_for_plan_file_stable should accept growing then stable file" >&2
      exit 1
    fi
  '
) || fail=1

# --- run_work_plan_gate skip-agent path ---
(
  cd "$FIXTURE"
  AIH_SKIP_AGENT=1 RUN_ID=test-gate bash -c '
    source ./ai-harness/scripts/lib/common.sh
    require_harness_deps
    ensure_runs_dir
    cp "'"$PLAN_EPHEMERAL"'" "$(work_plan_run_abs test-gate)"
    if run_work_plan_gate module-fast test-gate; then
      [[ -n "${AIH_WORK_PLAN_FILE:-}" ]] && echo "ok: run_work_plan_gate sets AIH_WORK_PLAN_FILE"
    else
      echo "FAIL: run_work_plan_gate should succeed with valid ephemeral plan" >&2
      exit 1
    fi
  '
) || fail=1

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
