#!/usr/bin/env bash
# Ephemeral Docker Compose stack for integration / API e2e tests (isolated from preview DB).
# Usage: test-stack.sh [up|reset|down|wait|status|export-env]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

ACTION="${1:-up}"
SERVICE_ARG="${2:-}"

require_harness_deps
cd "$REPO_ROOT"

if ! test_stack_configured; then
  echo "ERROR: test stack not configured (missing $(test_compose_active_when))" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker required for test stack" >&2
  exit 1
fi

test_stack_compose() {
  docker compose \
    -f "$REPO_ROOT/$(test_compose_file)" \
    -p "$(test_compose_project)" \
    "$@"
}

test_stack_health_timeout_ms() {
  jq -r '.computationalChecks.runtimeValidation.testStack.healthTimeoutMs // .computationalChecks.runtimeValidation.db.healthTimeoutMs // 60000' "$LOOP_CONFIG"
}

test_stack_service_status() {
  local service="$1"
  test_stack_compose ps --status running --format json "$service" 2>/dev/null \
    | jq -r '(.Health | select(length > 0)) // .State // empty' 2>/dev/null || true
}

test_stack_service_is_ready() {
  local status="$1"
  [[ "$status" == "healthy" || "$status" == "running" ]]
}

test_stack_wait_service() {
  local service="$1"
  local timeout_ms="${2:-$(test_stack_health_timeout_ms)}"
  local deadline=$(( $(date +%s) * 1000 + timeout_ms ))
  local status
  while true; do
    status="$(test_stack_service_status "$service")"
    if test_stack_service_is_ready "$status"; then
      return 0
    fi
    if (( $(date +%s) * 1000 >= deadline )); then
      echo "ERROR: test stack service '${service}' not ready (status: ${status:-not running})" >&2
      return 1
    fi
    sleep 2
  done
}

test_stack_wait_all() {
  local service
  while IFS= read -r service; do
    [[ -z "$service" ]] && continue
    test_stack_wait_service "$service" || return 1
  done < <(test_stack_service_names)
}

test_stack_up_services() {
  local -a services=()
  while IFS= read -r svc; do
    [[ -z "$svc" ]] && continue
    services+=("$svc")
  done < <(test_stack_service_names)
  test_stack_compose up -d "${services[@]}"
}

test_stack_down_services() {
  test_stack_compose down -v --remove-orphans 2>/dev/null || true
}

cmd_status() {
  local service="${SERVICE_ARG}"
  if [[ -n "$service" ]]; then
    test_stack_service_status "$service"
    return 0
  fi
  while IFS= read -r svc; do
    [[ -z "$svc" ]] && continue
    printf '%s:%s\n' "$svc" "$(test_stack_service_status "$svc")"
  done < <(test_stack_service_names)
}

case "$ACTION" in
  up)
    test_stack_up_services
    test_stack_wait_all
    ;;
  reset)
    if [[ "${AIH_TEST_STACK_RESET:-1}" == "1" ]]; then
      test_stack_down_services
    fi
    test_stack_up_services
    test_stack_wait_all
    ;;
  down)
    test_stack_down_services
    ;;
  wait)
    test_stack_wait_all
    ;;
  status)
    cmd_status
    ;;
  export-env)
    export_test_stack_env
    env | grep -E '^(DATABASE_URL|TEST_DATABASE_URL|REDIS_URL|TEST_REDIS_URL|S3_ENDPOINT|TEST_S3_ENDPOINT)=' || true
    ;;
  -h|--help)
    cat <<'EOF'
Usage: test-stack.sh [up|reset|down|wait|status|export-env]

  up         Start test compose services and wait for health
  reset      down -v then up (clean state; default for harness checks)
  down       Stop test stack and remove ephemeral volumes
  wait       Poll until all configured services are healthy or running
  status     Print service readiness (all as name:status, or one service name only)
  export-env Print test-stack connection env vars

Override: AIH_TEST_STACK_RESET=0 skips volume teardown on reset (faster local iteration).
EOF
    exit 0
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    exit 1
    ;;
esac
