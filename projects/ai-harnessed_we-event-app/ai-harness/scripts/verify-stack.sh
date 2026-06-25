#!/usr/bin/env bash
# Poll API health and web HTTP until startup succeeds or timeout.
# Usage: verify-stack.sh [--quick]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

QUICK=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) QUICK=true; shift ;;
    -h|--help)
      echo "Usage: verify-stack.sh [--quick]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

require_harness_deps
require_cmd curl

API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
WEB_PORT="${AIH_PREVIEW_WEB_PORT:-3000}"
MODE="${AIH_PREVIEW_MODE:-dev}"

if [[ -z "${AIH_VERIFY_API_TIMEOUT_MS:-}" ]]; then
  [[ "$MODE" == "full" ]] && AIH_VERIFY_API_TIMEOUT_MS=180000 || AIH_VERIFY_API_TIMEOUT_MS=60000
fi
if [[ -z "${AIH_VERIFY_WEB_TIMEOUT_MS:-}" ]]; then
  [[ "$MODE" == "full" ]] && AIH_VERIFY_WEB_TIMEOUT_MS=180000 || AIH_VERIFY_WEB_TIMEOUT_MS=120000
fi

API_URL="http://localhost:${API_PORT}/api/v1/health"
WEB_URL="http://localhost:${WEB_PORT}/"

api_healthy() {
  local body="$1"
  local status db
  status="$(echo "$body" | jq -r '.status // empty' 2>/dev/null || true)"
  db="$(echo "$body" | jq -r '.db // empty' 2>/dev/null || true)"
  [[ "$status" == "ok" && "$db" == "connected" ]]
}

poll_api() {
  local deadline=$(( $(date +%s) * 1000 + AIH_VERIFY_API_TIMEOUT_MS ))
  local body
  while true; do
    if body="$(curl -sf "$API_URL" 2>/dev/null || true)" && [[ -n "$body" ]]; then
      if api_healthy "$body"; then
        echo "API healthy: $API_URL"
        return 0
      fi
    else
      body="(no response)"
      if [[ "$QUICK" == true ]]; then
        return 0
      fi
    fi
    if [[ "$QUICK" == true ]]; then
      echo "ERROR: API unhealthy" >&2
      echo "  URL: $API_URL" >&2
      echo "  Last response: $body" >&2
      return 1
    fi
    if (( $(date +%s) * 1000 >= deadline )); then
      echo "ERROR: API startup failed after ${AIH_VERIFY_API_TIMEOUT_MS}ms" >&2
      echo "  URL: $API_URL" >&2
      echo "  Last response: $body" >&2
      return 1
    fi
    sleep 2
  done
}

poll_web() {
  local deadline=$(( $(date +%s) * 1000 + AIH_VERIFY_WEB_TIMEOUT_MS ))
  local code
  while true; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$WEB_URL" 2>/dev/null || true)"
    [[ -z "$code" ]] && code="000"
    if [[ "$code" == "200" ]]; then
      echo "Web ready: $WEB_URL (HTTP $code)"
      return 0
    fi
    if [[ "$code" == "000" && "$QUICK" == true ]]; then
      return 0
    fi
    if [[ "$QUICK" == true ]]; then
      echo "ERROR: Web unhealthy" >&2
      echo "  URL: $WEB_URL" >&2
      echo "  Last HTTP status: $code" >&2
      return 1
    fi
    if (( $(date +%s) * 1000 >= deadline )); then
      echo "ERROR: Web startup failed after ${AIH_VERIFY_WEB_TIMEOUT_MS}ms" >&2
      echo "  URL: $WEB_URL" >&2
      echo "  Last HTTP status: $code" >&2
      return 1
    fi
    sleep 2
  done
}

cd "$REPO_ROOT"
poll_api
poll_web
echo "Stack startup verification passed (mode=$MODE)"
