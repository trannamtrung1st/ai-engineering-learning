#!/usr/bin/env bash
# Computational validation gates
# Usage: run-checks.sh [sliceId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
ensure_runs_dir

# Omit slice id for global checks only (docs-only repo). Ralph passes slice id explicitly.
SLICE_ID="${1:-${AIH_CHECK_SLICE:-}}"
RID="$(run_id)"
FAILURES=()
PASS=true

cd "$REPO_ROOT"

check_forbidden_patterns() {
  local has_code=false
  for dir in apps packages; do
    [[ -d "$dir" ]] && has_code=true
  done
  if [[ "$has_code" == false ]]; then
    return 0
  fi

  while IFS= read -r entry; do
    [[ -z "$entry" ]] && continue
    local id pattern paths message
    id="$(echo "$entry" | jq -r '.id')"
    pattern="$(echo "$entry" | jq -r '.pattern')"
    message="$(echo "$entry" | jq -r '.message')"
    local search_paths=()
    local p
    while IFS= read -r p; do
      [[ -d "$REPO_ROOT/$p" ]] && search_paths+=("$p")
    done < <(echo "$entry" | jq -r '.paths[]?')

    [[ ${#search_paths[@]} -eq 0 ]] && continue

    if search_files "$pattern" "${search_paths[@]}" | head -1 | grep -q .; then
      local match
      match="$(search_files "$pattern" "${search_paths[@]}" | head -3 | tr '\n' ', ')"
      FAILURES+=("{\"type\":\"forbidden_pattern\",\"id\":\"$id\",\"message\":\"$message\",\"files\":\"$match\"}")
      PASS=false
    fi
  done < <(jq -c '.computationalChecks.forbiddenPatterns[]' "$LOOP_CONFIG")
}

check_artifacts() {
  [[ -z "$SLICE_ID" ]] && return 0
  local slice_json
  slice_json="$(get_slice_json "$SLICE_ID")"
  [[ -z "$slice_json" || "$slice_json" == "null" ]] && return 0

  local artifact
  while IFS= read -r artifact; do
    [[ -z "$artifact" ]] && continue
    if [[ ! -e "$REPO_ROOT/$artifact" ]]; then
      FAILURES+=("{\"type\":\"missing_artifact\",\"path\":\"$artifact\"}")
      PASS=false
    fi
  done < <(echo "$slice_json" | jq -r '.completionArtifacts[]?')
}

check_npm_commands() {
  [[ -f package.json ]] || return 0
  local script optional active_when
  while IFS= read -r line; do
    script="$(echo "$line" | jq -r '.script')"
    optional="$(echo "$line" | jq -r '.optional // true')"
    active_when="$(echo "$line" | jq -r '.activeWhen // empty')"
    if [[ -n "$active_when" && ! -e "$REPO_ROOT/$active_when" ]]; then
      continue
    fi
    if jq -e --arg s "$script" '.scripts[$s]' package.json >/dev/null 2>&1; then
      if ! npm run "$script" 2>&1; then
        FAILURES+=("{\"type\":\"npm_script\",\"script\":\"$script\"}")
        PASS=false
      fi
    elif [[ "$optional" != "true" ]]; then
      FAILURES+=("{\"type\":\"npm_script_missing\",\"script\":\"$script\"}")
      PASS=false
    fi
  done < <(jq -c '.computationalChecks.commands[]?' "$LOOP_CONFIG")
}

check_db_runtime() {
  local active_when
  active_when="$(jq -r '.computationalChecks.runtimeValidation.db.activeWhen // "docker-compose.yml"' "$LOOP_CONFIG")"
  [[ -f "$REPO_ROOT/$active_when" ]] || return 0

  if ! command -v docker >/dev/null 2>&1; then
    FAILURES+=("{\"type\":\"runtime\",\"message\":\"docker not available for db validation\"}")
    PASS=false
    return
  fi

  local service
  service="$(jq -r '.computationalChecks.runtimeValidation.db.service // "db"' "$LOOP_CONFIG")"
  local status
  status="$(docker compose ps --status running --format json "$service" 2>/dev/null | jq -r '.Health // .State // empty' 2>/dev/null || true)"
  if [[ "$status" != "healthy" && "$status" != "running" ]]; then
    # Only fail if apps/api exists (implementation phase)
    if [[ -d apps/api ]]; then
      FAILURES+=("{\"type\":\"runtime\",\"message\":\"db service not healthy (status: ${status:-not running})\"}")
      PASS=false
    fi
  fi

  if [[ -f package-lock.json ]] && file_contains 'better-sqlite3|sqlite3' package-lock.json; then
    FAILURES+=("{\"type\":\"runtime\",\"message\":\"SQLite dependency found in lockfile\"}")
    PASS=false
  fi
}

check_stack_startup() {
  local api_when web_when
  api_when="$(jq -r '.computationalChecks.runtimeValidation.api.activeWhen // empty' "$LOOP_CONFIG")"
  web_when="$(jq -r '.computationalChecks.runtimeValidation.web.activeWhen // empty' "$LOOP_CONFIG")"
  [[ -n "$api_when" && -d "$REPO_ROOT/$api_when" ]] || return 0
  [[ -n "$web_when" && -d "$REPO_ROOT/$web_when" ]] || return 0

  local verify_script scenario_script
  local verify_args=()
  local stack_out scenario_out
  verify_script="$(dirname "$0")/verify-stack.sh"
  scenario_script="$(dirname "$0")/verify-scenarios.sh"
  [[ -x "$verify_script" ]] || return 0

  if [[ "${AIH_VERIFY_STACK:-}" == "1" ]]; then
    verify_args=()
  else
    verify_args=(--quick)
  fi

  if ! slice_requires_web_runtime "$SLICE_ID"; then
    verify_args+=(--api-only)
  fi

  set +e
  stack_out="$("$verify_script" "${verify_args[@]}" 2>&1)"
  local stack_status=$?
  set -e
  echo "$stack_out"

  if [[ "$stack_status" -ne 0 ]]; then
    local failure_msg="stack startup verification failed"
    if echo "$stack_out" | grep -q "API unhealthy"; then
      failure_msg="API startup verification failed"
    elif echo "$stack_out" | grep -q "Web unhealthy"; then
      failure_msg="web startup verification failed"
    fi
    FAILURES+=("{\"type\":\"runtime\",\"message\":\"${failure_msg}\"}")
    PASS=false
  fi

  if [[ ! -x "$scenario_script" ]]; then
    return 0
  fi

  local scenario_args=()
  if [[ "${AIH_VERIFY_STACK:-}" != "1" ]]; then
    scenario_args=(--quick)
  fi

  set +e
  scenario_out="$("$scenario_script" "${scenario_args[@]}" 2>&1)"
  local scenario_status=$?
  set -e
  echo "$scenario_out"

  if [[ "$scenario_status" -ne 0 ]]; then
    FAILURES+=("{\"type\":\"runtime\",\"message\":\"participant registration scenario probe failed\"}")
    PASS=false
  fi
}

check_forbidden_patterns
check_artifacts
check_npm_commands
refresh_preview_web_after_build
check_db_runtime
check_stack_startup

# Build JSON report
failures_json="[]"
if [[ ${#FAILURES[@]} -gt 0 ]]; then
  failures_json="[$(IFS=,; echo "${FAILURES[*]}")]"
fi

report="$(jq -n \
  --arg slice "$SLICE_ID" \
  --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
  --argjson pass "$([ "$PASS" = true ] && echo true || echo false)" \
  --argjson failures "$failures_json" \
  '{slice: $slice, timestamp: $ts, pass: $pass, failures: $failures}')"

write_run_report "${RID}-checks.json" "$report"
echo "$report"

if [[ "$PASS" == true ]]; then
  exit 0
fi
exit 1
