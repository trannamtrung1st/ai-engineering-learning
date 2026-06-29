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

# Run a shell command with begin → output → pass/fail logging.
run_shell_check() {
  local label="$1"
  shift
  aih_check_begin "$label"
  local out status
  set +e
  out="$("$@" 2>&1)"
  status=$?
  set -e
  if [[ -n "$out" ]]; then
    echo "$out"
  fi
  if [[ "$status" -eq 0 ]]; then
    aih_check_ok "$label"
    return 0
  fi
  aih_check_fail "$label (exit ${status})"
  return 1
}

check_forbidden_patterns() {
  local has_code=false
  for dir in apps packages; do
    [[ -d "$dir" ]] && has_code=true
  done
  if [[ "$has_code" == false ]]; then
    aih_check_skip "forbidden pattern scan (no apps/ or packages/)"
    return 0
  fi

  aih_check_begin "forbidden pattern scan"
  local failed=false
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
      failed=true
      aih_err "forbidden pattern ${id}: ${message} (${match})"
    fi
  done < <(jq -c '.computationalChecks.forbiddenPatterns[]' "$LOOP_CONFIG")

  if [[ "$failed" == true ]]; then
    aih_check_fail "forbidden pattern scan"
  else
    aih_check_ok "forbidden pattern scan"
  fi
}

check_artifacts() {
  if [[ -z "$SLICE_ID" ]]; then
    aih_check_skip "slice completion artifacts (no slice id)"
    return 0
  fi
  local slice_json
  slice_json="$(get_slice_json "$SLICE_ID")"
  [[ -z "$slice_json" || "$slice_json" == "null" ]] && return 0

  aih_check_begin "slice completion artifacts (${SLICE_ID})"
  local failed=false artifact
  while IFS= read -r artifact; do
    [[ -z "$artifact" ]] && continue
    if [[ ! -e "$REPO_ROOT/$artifact" ]]; then
      FAILURES+=("{\"type\":\"missing_artifact\",\"path\":\"$artifact\"}")
      PASS=false
      failed=true
      aih_err "missing artifact: ${artifact}"
    fi
  done < <(echo "$slice_json" | jq -r '.completionArtifacts[]?')

  if [[ "$failed" == true ]]; then
    aih_check_fail "slice completion artifacts (${SLICE_ID})"
  else
    aih_check_ok "slice completion artifacts (${SLICE_ID})"
  fi
}

check_slice_test_requirements() {
  if [[ -z "$SLICE_ID" ]]; then
    aih_check_skip "slice testRequirements (no slice id)"
    return 0
  fi
  local slice_json
  slice_json="$(get_slice_json "$SLICE_ID")"
  [[ -z "$slice_json" || "$slice_json" == "null" ]] && return 0
  if ! echo "$slice_json" | jq -e '.testRequirements' >/dev/null 2>&1; then
    aih_check_skip "slice testRequirements (none declared)"
    return 0
  fi

  aih_check_begin "slice testRequirements (${SLICE_ID})"
  local failed=false layer path tag
  for layer in unit integration component; do
    while IFS= read -r path; do
      [[ -z "$path" ]] && continue
      if [[ ! -e "$REPO_ROOT/$path" ]]; then
        FAILURES+=("{\"type\":\"missing_test\",\"layer\":\"$layer\",\"path\":\"$path\"}")
        PASS=false
        failed=true
        aih_err "missing ${layer} test file: ${path}"
      fi
    done < <(echo "$slice_json" | jq -r --arg layer "$layer" '.testRequirements[$layer][]?')
  done

  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    local found=false
    local match
    if command -v rg >/dev/null 2>&1; then
      match="$(rg -l "$tag" apps/api tests/e2e apps/web \
        -g '*.test.ts' -g '*.test.tsx' -g '*.integration.test.ts' 2>/dev/null | head -1 || true)"
    else
      match="$(grep -Ril "$tag" apps/api tests/e2e apps/web --include='*.test.ts' --include='*.test.tsx' --include='*.integration.test.ts' 2>/dev/null | head -1 || true)"
    fi
    [[ -n "$match" ]] && found=true
    if [[ "$found" != true ]]; then
      FAILURES+=("{\"type\":\"missing_test\",\"layer\":\"acceptance\",\"tag\":\"$tag\"}")
      PASS=false
      failed=true
      aih_err "acceptance tag not referenced in tests: ${tag}"
    fi
  done < <(echo "$slice_json" | jq -r '.testRequirements.acceptanceTags[]?')

  if [[ "$failed" == true ]]; then
    aih_check_fail "slice testRequirements (${SLICE_ID})"
  else
    aih_check_ok "slice testRequirements (${SLICE_ID})"
  fi
}

check_generated_test_case_coverage() {
  if [[ -z "$SLICE_ID" ]]; then
    aih_check_skip "generated test case coverage (no slice id)"
    return 0
  fi
  if ! slice_test_cases_current "$SLICE_ID"; then
    aih_check_skip "generated test case coverage (test cases not current)"
    return 0
  fi

  aih_check_begin "generated test case coverage (${SLICE_ID})"
  local failed=false ref artifact case_id layer tag found match
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    artifact="$(test_case_artifact_abs "$ref")"
    [[ -f "$artifact" ]] || continue

    while IFS=$'\t' read -r case_id layer tags; do
      [[ -z "$case_id" ]] && continue
      [[ "$layer" == "browser" ]] && continue

      for tag in $(echo "$tags" | tr ',' ' '); do
        [[ -z "$tag" ]] && continue
        found=false
        if command -v rg >/dev/null 2>&1; then
          match="$(rg -l "$tag" apps/api tests/e2e apps/web packages/domain \
            -g '*.test.ts' -g '*.test.tsx' -g '*.integration.test.ts' 2>/dev/null | head -1 || true)"
        else
          match="$(grep -Ril "$tag" apps/api tests/e2e apps/web packages/domain \
            --include='*.test.ts' --include='*.test.tsx' --include='*.integration.test.ts' 2>/dev/null | head -1 || true)"
        fi
        [[ -n "$match" ]] && found=true
        if [[ "$found" != true ]]; then
          FAILURES+=("{\"type\":\"missing_test_case_coverage\",\"productItem\":\"$ref\",\"caseId\":\"$case_id\",\"layer\":\"$layer\",\"tag\":\"$tag\"}")
          PASS=false
          failed=true
          aih_err "missing coverage for ${case_id} (${layer}, tag ${tag})"
        fi
      done
    done < <(jq -r '.cases[] | select(.layer == "integration" or .layer == "e2e") | [.id, .layer, (.traceability | join(","))] | @tsv' "$artifact")
  done < <(slice_product_item_refs "$SLICE_ID")

  if [[ "$failed" == true ]]; then
    aih_check_fail "generated test case coverage (${SLICE_ID})"
  else
    aih_check_ok "generated test case coverage (${SLICE_ID})"
  fi
}

check_npm_commands() {
  if [[ ! -f package.json ]]; then
    aih_check_skip "npm scripts (no package.json)"
    return 0
  fi

  local script optional active_when label
  while IFS= read -r line; do
    script="$(echo "$line" | jq -r '.script')"
    optional="$(echo "$line" | jq -r '.optional // true')"
    active_when="$(echo "$line" | jq -r '.activeWhen // empty')"
    if [[ -n "$active_when" && ! -e "$REPO_ROOT/$active_when" ]]; then
      aih_check_skip "npm run ${script} (inactive — ${active_when} missing)"
      continue
    fi
    if jq -e --arg s "$script" '.scripts[$s]' package.json >/dev/null 2>&1; then
      if [[ "$script" == "build" ]]; then
        label="npm run build (preview-aware workspace build)"
        aih_check_begin "$label"
        local out status
        set +e
        out="$(run_build_for_checks 2>&1)"
        status=$?
        set -e
        if [[ -n "$out" ]]; then
          echo "$out"
        fi
        if [[ "$status" -ne 0 ]]; then
          aih_check_fail "$label (exit ${status})"
          FAILURES+=("{\"type\":\"npm_script\",\"script\":\"$script\"}")
          PASS=false
        else
          aih_check_ok "$label"
        fi
      else
        label="npm run ${script}"
        if ! run_shell_check "$label" npm run "$script"; then
          FAILURES+=("{\"type\":\"npm_script\",\"script\":\"$script\"}")
          PASS=false
        fi
      fi
    elif [[ "$optional" != "true" ]]; then
      label="npm run ${script}"
      aih_check_begin "$label"
      aih_check_fail "required npm script missing from package.json"
      FAILURES+=("{\"type\":\"npm_script_missing\",\"script\":\"$script\"}")
      PASS=false
    else
      aih_check_skip "npm run ${script} (optional script missing)"
    fi
  done < <(jq -c '.computationalChecks.commands[]?' "$LOOP_CONFIG")
}

db_compose_status() {
  local service="$1"
  docker compose ps --status running --format json "$service" 2>/dev/null \
    | jq -r '.Health // .State // empty' 2>/dev/null || true
}

wait_db_compose_healthy() {
  local service="$1"
  local timeout_ms="${2:-60000}"
  local deadline=$(( $(date +%s) * 1000 + timeout_ms ))
  local status
  while true; do
    status="$(db_compose_status "$service")"
    if [[ "$status" == "healthy" || "$status" == "running" ]]; then
      return 0
    fi
    if (( $(date +%s) * 1000 >= deadline )); then
      return 1
    fi
    sleep 2
  done
}

check_db_runtime() {
  local active_when
  active_when="$(jq -r '.computationalChecks.runtimeValidation.db.activeWhen // "docker-compose.yml"' "$LOOP_CONFIG")"
  if [[ ! -f "$REPO_ROOT/$active_when" ]]; then
    aih_check_skip "db runtime validation (${active_when} missing)"
    return 0
  fi

  local service health_timeout_ms status label
  service="$(jq -r '.computationalChecks.runtimeValidation.db.service // "db"' "$LOOP_CONFIG")"
  label="db runtime validation (docker compose service: ${service})"
  aih_check_begin "$label"
  local failed=false

  if ! command -v docker >/dev/null 2>&1; then
    FAILURES+=("{\"type\":\"runtime\",\"message\":\"docker not available for db validation\"}")
    PASS=false
    aih_check_fail "docker not available"
    return
  fi

  health_timeout_ms="$(jq -r '.computationalChecks.runtimeValidation.db.healthTimeoutMs // 60000' "$LOOP_CONFIG")"
  status="$(db_compose_status "$service")"
  if [[ "$status" != "healthy" && "$status" != "running" ]]; then
    if [[ -d apps/api ]]; then
      aih_info "    starting ${service} (status: ${status:-not running})"
      if jq -e --arg s "aih:dev:db:up" '.scripts[$s]' package.json >/dev/null 2>&1; then
        npm run aih:dev:db:up >/dev/null 2>&1 || docker compose up -d "$service" >/dev/null 2>&1 || true
      else
        docker compose up -d "$service" >/dev/null 2>&1 || true
      fi
      if ! wait_db_compose_healthy "$service" "$health_timeout_ms"; then
        status="$(db_compose_status "$service")"
        FAILURES+=("{\"type\":\"runtime\",\"message\":\"db service not healthy (status: ${status:-not running})\"}")
        PASS=false
        failed=true
        aih_err "db service not healthy (status: ${status:-not running})"
      fi
    fi
  else
    aih_info "    ${service} status: ${status}"
  fi

  if [[ -f package-lock.json ]] && file_contains 'better-sqlite3|sqlite3' package-lock.json; then
    FAILURES+=("{\"type\":\"runtime\",\"message\":\"SQLite dependency found in lockfile\"}")
    PASS=false
    failed=true
    aih_err "SQLite dependency found in package-lock.json"
  fi

  if [[ "$failed" == true ]]; then
    aih_check_fail "$label"
  else
    aih_check_ok "$label"
  fi
}

refresh_preview_web_after_build_logged() {
  [[ -d "$REPO_ROOT/apps/web" ]] || return 0
  if preview_stack_is_running; then
    aih_check_skip "refresh preview web cache (preview stack running)"
    return 0
  fi
  aih_check_begin "refresh preview web cache (post-build)"
  stop_preview_web_process
  clean_web_next_cache
  aih_check_ok "refresh preview web cache (post-build)"
}

check_stack_startup() {
  local api_when web_when
  api_when="$(jq -r '.computationalChecks.runtimeValidation.api.activeWhen // empty' "$LOOP_CONFIG")"
  web_when="$(jq -r '.computationalChecks.runtimeValidation.web.activeWhen // empty' "$LOOP_CONFIG")"
  if [[ -z "$api_when" || ! -d "$REPO_ROOT/$api_when" ]]; then
    aih_check_skip "stack startup probe (api inactive)"
    return 0
  fi
  if [[ -z "$web_when" || ! -d "$REPO_ROOT/$web_when" ]]; then
    aih_check_skip "stack startup probe (web inactive)"
    return 0
  fi

  local verify_script scenario_script
  local verify_args=()
  local stack_out scenario_out stack_label scenario_label
  verify_script="$(dirname "$0")/verify-stack.sh"
  scenario_script="$(dirname "$0")/verify-scenarios.sh"
  if [[ ! -x "$verify_script" ]]; then
    aih_check_skip "stack startup probe (verify-stack.sh missing)"
    return 0
  fi

  if [[ "${AIH_VERIFY_STACK:-}" == "1" ]]; then
    verify_args=()
    stack_label="./ai-harness/scripts/verify-stack.sh"
  else
    verify_args=(--quick)
    stack_label="./ai-harness/scripts/verify-stack.sh --quick"
  fi

  if ! slice_requires_web_runtime "$SLICE_ID"; then
    verify_args+=(--api-only)
    stack_label="${stack_label} --api-only"
  fi

  aih_check_begin "$stack_label"
  set +e
  if [[ ${#verify_args[@]} -gt 0 ]]; then
    stack_out="$("$verify_script" "${verify_args[@]}" 2>&1)"
  else
    stack_out="$("$verify_script" 2>&1)"
  fi
  local stack_status=$?
  set -e
  if [[ -n "$stack_out" ]]; then
    echo "$stack_out"
  fi

  if [[ "$stack_status" -ne 0 ]]; then
    local failure_msg="stack startup verification failed"
    if echo "$stack_out" | grep -q "API unhealthy"; then
      failure_msg="API startup verification failed"
    elif echo "$stack_out" | grep -q "Web unhealthy"; then
      failure_msg="web startup verification failed"
    fi
    aih_check_fail "$stack_label (exit ${stack_status})"
    FAILURES+=("{\"type\":\"runtime\",\"message\":\"${failure_msg}\"}")
    PASS=false
  else
    aih_check_ok "$stack_label"
  fi

  if [[ ! -x "$scenario_script" ]]; then
    aih_check_skip "scenario probe (verify-scenarios.sh missing)"
    return 0
  fi

  local scenario_args=()
  if [[ "${AIH_VERIFY_STACK:-}" != "1" ]]; then
    scenario_args=(--quick)
    scenario_label="./ai-harness/scripts/verify-scenarios.sh --quick"
  else
    scenario_label="./ai-harness/scripts/verify-scenarios.sh"
  fi

  aih_check_begin "$scenario_label"
  set +e
  if [[ ${#scenario_args[@]} -gt 0 ]]; then
    scenario_out="$("$scenario_script" "${scenario_args[@]}" 2>&1)"
  else
    scenario_out="$("$scenario_script" 2>&1)"
  fi
  local scenario_status=$?
  set -e
  if [[ -n "$scenario_out" ]]; then
    echo "$scenario_out"
  fi

  if [[ "$scenario_status" -ne 0 ]]; then
    aih_check_fail "$scenario_label (exit ${scenario_status})"
    FAILURES+=("{\"type\":\"runtime\",\"message\":\"participant registration scenario probe failed\"}")
    PASS=false
  else
    aih_check_ok "$scenario_label"
  fi
}

if [[ -n "$SLICE_ID" ]]; then
  aih_info "Computational checks for slice: ${SLICE_ID}"
else
  aih_info "Computational checks (global — no slice id)"
fi
aih_blank

check_forbidden_patterns
check_artifacts
check_slice_test_requirements
check_generated_test_case_coverage
check_db_runtime
check_npm_commands
refresh_preview_web_after_build_logged
check_stack_startup

aih_blank
if [[ "$PASS" == true ]]; then
  aih_ok "All computational checks passed"
else
  aih_err "Computational checks failed (${#FAILURES[@]} failure(s))"
fi

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
aih_info "Report: ${RID}-checks.json"
echo "$report"

if [[ "$PASS" == true ]]; then
  exit 0
fi
exit 1
