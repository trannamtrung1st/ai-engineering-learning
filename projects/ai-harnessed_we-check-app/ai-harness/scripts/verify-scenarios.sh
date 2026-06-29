#!/usr/bin/env bash
# We Check live-stack scenario probe (auth envelope smoke test).
# Usage: verify-scenarios.sh [--quick]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

QUICK=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) QUICK=true; shift ;;
    -h|--help)
      echo "Usage: verify-scenarios.sh [--quick]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

require_harness_deps
require_cmd curl

API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
API_BASE="http://localhost:${API_PORT}/api/v1"

api_healthy() {
  local body="$1"
  local status db
  status="$(echo "$body" | jq -r '.status // empty' 2>/dev/null || true)"
  db="$(echo "$body" | jq -r '.db // empty' 2>/dev/null || true)"
  [[ "$status" == "ok" && "$db" == "connected" ]]
}

health_body="$(curl --connect-timeout 2 --max-time 5 -sf "${API_BASE}/health" 2>/dev/null || true)"
if [[ -z "$health_body" ]] || ! api_healthy "$health_body"; then
  if [[ "$QUICK" == true ]]; then
    echo "SKIP: API not running (We Check scenario probe)"
    exit 0
  fi
  echo "ERROR: API unhealthy — cannot run We Check scenario probe" >&2
  echo "  URL: ${API_BASE}/health" >&2
  echo "  Last response: ${health_body:-"(no response)"}" >&2
  exit 1
fi

login_tmp="$(mktemp)"
trap 'rm -f "$login_tmp"' EXIT

login_code="$(curl --connect-timeout 2 --max-time 5 -s -o "$login_tmp" -w '%{http_code}' \
  -X POST "${API_BASE}/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"probe@example.edu.vn","password":"wrong-password"}')"

if [[ "$login_code" != "401" ]]; then
  echo "ERROR: auth/login probe expected HTTP 401, got ${login_code}" >&2
  cat "$login_tmp" >&2
  exit 1
fi

error_code="$(jq -r '.errorCode // empty' "$login_tmp" 2>/dev/null || true)"
message="$(jq -r '.message // empty' "$login_tmp" 2>/dev/null || true)"

if [[ "$error_code" != "InvalidCredentials" ]]; then
  echo "ERROR: auth/login probe expected errorCode InvalidCredentials, got '${error_code}'" >&2
  cat "$login_tmp" >&2
  exit 1
fi

if [[ -z "$message" ]] || [[ "$message" == "InvalidCredentials" ]]; then
  echo "ERROR: auth/login probe expected Vietnamese message, got '${message}'" >&2
  cat "$login_tmp" >&2
  exit 1
fi

echo "We Check auth scenario passed (InvalidCredentials localized, message=${message})"
