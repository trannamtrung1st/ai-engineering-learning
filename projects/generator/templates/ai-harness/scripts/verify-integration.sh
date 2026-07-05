#!/usr/bin/env bash
# Mechanical integration debt checks — reads ai-harness/config/integration-checks.json.
# Usage: verify-integration.sh [--check all|app-module|e2e-harness|seed-scripts|fixture-flag|compose|jwt-env]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

CHECK="${1:-all}"
if [[ "$CHECK" == "--check" ]]; then
  CHECK="${2:-all}"
fi

CONFIG="${REPO_ROOT}/ai-harness/config/integration-checks.json"
PASS=true
FAILURES=()

fail() {
  FAILURES+=("$1")
  PASS=false
}

pass_msg() {
  if [[ "${AIH_VERIFY_INTEGRATION_VERBOSE:-}" == "1" ]]; then
    aih_ok "$1"
  fi
}

load_config() {
  if [[ ! -f "$CONFIG" ]]; then
    fail "missing $CONFIG (harness-planner should emit populated integration-checks.json)"
    return 1
  fi
  if ! jq empty "$CONFIG" >/dev/null 2>&1; then
    fail "invalid JSON: $CONFIG"
    return 1
  fi
}

if ! load_config; then
  echo "Integration verification FAILED ($CHECK):" >&2
  printf '  - %s\n' "${FAILURES[@]}" >&2
  echo "See ai-harness/docs/integration-debt-register.md" >&2
  exit 1
fi

check_app_module() {
  local app_module
  app_module="$(jq -r '.appModulePath // "apps/api/src/app.module.ts"' "$CONFIG")"
  [[ -f "$app_module" ]] || { fail "missing $app_module"; return; }

  local modules=()
  while IFS= read -r mod; do
    [[ -z "$mod" ]] && continue
    modules+=("$mod")
  done < <(jq -r '.requiredModules[]? // empty' "$CONFIG")

  if [[ "${#modules[@]}" -eq 0 ]]; then
    fail "integration-checks.json requiredModules is empty (populate via harness-planner from module breakdown)"
    return
  fi

  for mod in "${modules[@]}"; do
    if ! grep -q "$mod" "$app_module"; then
      fail "AppModule missing import: $mod (slice api-app-module-wiring)"
    else
      pass_msg "AppModule includes $mod"
    fi
  done
}

check_e2e_harness() {
  local e2e_app
  e2e_app="$(jq -r '.e2eHarnessPath // "tests/e2e/src/support/create-e2e-app.ts"' "$CONFIG")"
  [[ -f "$e2e_app" ]] || { fail "missing $e2e_app"; return; }

  local modules=()
  while IFS= read -r mod; do
    [[ -z "$mod" ]] && continue
    modules+=("$mod")
  done < <(jq -r '.e2eRequiredModules[]? // .requiredModules[]? // empty' "$CONFIG")

  if [[ "${#modules[@]}" -eq 0 ]]; then
    aih_warn "e2eRequiredModules empty — skipping E2E harness module checks"
    return
  fi

  for mod in "${modules[@]}"; do
    if ! grep -q "$mod" "$e2e_app"; then
      fail "E2E harness missing import: $mod (slice api-app-module-wiring)"
    else
      pass_msg "E2E harness includes $mod"
    fi
  done
}

check_seed_scripts() {
  local script
  while IFS= read -r script; do
    [[ -z "$script" ]] && continue
    if ! jq -e --arg s "$script" '.scripts[$s]' package.json >/dev/null 2>&1; then
      fail "root package.json missing script \"${script}\" (slice db-migrate-seed-preview)"
    else
      pass_msg "${script} script present"
    fi
  done < <(jq -r '.requiredNpmScripts[]? // empty' "$CONFIG")
}

check_fixture_flag() {
  local env_var helper
  env_var="$(jq -r '.fixtureEnvVar // "VITE_PREVIEW_FIXTURE_MODE"' "$CONFIG")"
  helper="$(jq -r '.fixtureHelperPath // empty' "$CONFIG")"

  if [[ -n "$helper" && "$helper" != "null" ]]; then
    if [[ ! -f "$helper" ]]; then
      fail "missing $helper (slice web-harness-fixture-gating)"
      return
    fi
    if ! grep -q "$env_var" "$helper"; then
      fail "$helper must gate on $env_var"
    else
      pass_msg "Harness fixture gating helper present"
    fi
  else
    aih_warn "fixtureHelperPath empty — skipping fixture helper check"
  fi

  if [[ -f .env.example ]] && ! grep -q "$env_var" .env.example 2>/dev/null; then
    fail ".env.example should document $env_var"
  fi
}

check_compose() {
  local profile service
  local has_profiles=false has_services=false

  if jq -e '.composeProfiles | length > 0' "$CONFIG" >/dev/null 2>&1; then
    has_profiles=true
  fi
  if jq -e '.composeServices | length > 0' "$CONFIG" >/dev/null 2>&1; then
    has_services=true
  fi

  if [[ "$has_profiles" != true && "$has_services" != true ]]; then
    aih_warn "composeProfiles and composeServices empty — skipping compose checks"
    return
  fi

  [[ -f docker-compose.yml ]] || { fail "missing docker-compose.yml (slice compose-full-preview)"; return; }

  if [[ "$has_profiles" == true ]]; then
    while IFS= read -r profile; do
      [[ -z "$profile" ]] && continue
      if ! grep -q "$profile" docker-compose.yml 2>/dev/null; then
        fail "docker-compose.yml missing profile: $profile (slice compose-full-preview)"
      else
        pass_msg "Compose profile $profile present"
      fi
    done < <(jq -r '.composeProfiles[]? // empty' "$CONFIG")
  fi

  if [[ "$has_services" == true ]]; then
    while IFS= read -r service; do
      [[ -z "$service" ]] && continue
      if ! grep -q "${service}:" docker-compose.yml 2>/dev/null; then
        fail "docker-compose.yml missing service: $service (slice compose-full-preview)"
      else
        pass_msg "Compose service $service present"
      fi
    done < <(jq -r '.composeServices[]? // empty' "$CONFIG")
  fi

  for df in apps/api/Dockerfile apps/web/Dockerfile; do
    if [[ ! -f "$df" ]]; then
      fail "missing $df (slice compose-full-preview)"
    fi
  done
}

check_jwt_env() {
  local jwt_svc env_vars=()
  jwt_svc="$(jq -r '.jwtServicePath // empty' "$CONFIG")"
  if [[ -z "$jwt_svc" || "$jwt_svc" == "null" ]]; then
    aih_warn "jwtServicePath empty — skipping JWT env checks"
    return
  fi
  [[ -f "$jwt_svc" ]] || { fail "missing $jwt_svc (slice config-jwt-env-alignment)"; return; }

  while IFS= read -r var; do
    [[ -z "$var" ]] && continue
    env_vars+=("$var")
  done < <(jq -r '.jwtEnvVars[]? // empty' "$CONFIG")

  if [[ "${#env_vars[@]}" -eq 0 ]]; then
    aih_warn "jwtEnvVars empty — skipping JWT env checks"
    return
  fi

  local var
  for var in "${env_vars[@]}"; do
    if ! grep -q "$var" "$jwt_svc"; then
      fail "$jwt_svc must read $var (slice config-jwt-env-alignment)"
    else
      pass_msg "$jwt_svc references $var"
    fi
    if [[ -f .env.example ]] && ! grep -q "$var" .env.example 2>/dev/null; then
      fail ".env.example should document $var"
    fi
  done
}

case "$CHECK" in
  all)
    check_app_module
    check_e2e_harness
    check_seed_scripts
    check_fixture_flag
    check_compose
    check_jwt_env
    ;;
  app-module) check_app_module ;;
  e2e-harness) check_e2e_harness ;;
  seed-scripts) check_seed_scripts ;;
  fixture-flag) check_fixture_flag ;;
  compose) check_compose ;;
  jwt-env) check_jwt_env ;;
  -h|--help)
    echo "Usage: verify-integration.sh [--check all|app-module|e2e-harness|seed-scripts|fixture-flag|compose|jwt-env]"
    exit 0
    ;;
  *)
    fail "unknown check: $CHECK"
    ;;
esac

if [[ "$PASS" != true ]]; then
  echo "Integration verification FAILED ($CHECK):" >&2
  printf '  - %s\n' "${FAILURES[@]}" >&2
  echo "See ai-harness/docs/integration-debt-register.md" >&2
  exit 1
fi

echo "Integration verification passed ($CHECK)"
exit 0
