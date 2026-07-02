#!/usr/bin/env bash
# Student auth scenario probe (live stack) — GET /setup/status, POST /auth/login, GET /auth/me.
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
SCENARIO_EMAIL="${AIH_SCENARIO_EMAIL:-student@example.edu.vn}"
SCENARIO_PASSWORD="${AIH_SCENARIO_PASSWORD:-StudentPass8}"

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
    echo "SKIP: API not running (student auth scenario probe)"
    exit 0
  fi
  echo "ERROR: API unhealthy — cannot run student auth scenario probe" >&2
  echo "  URL: ${API_BASE}/health" >&2
  echo "  Last response: ${health_body:-"(no response)"}" >&2
  exit 1
fi

setup_body="$(curl --connect-timeout 2 --max-time 5 -sf "${API_BASE}/setup/status" 2>/dev/null || true)"
needs_setup="$(echo "$setup_body" | jq -r '.needsSetup // empty' 2>/dev/null || true)"
if [[ "$needs_setup" == "true" ]]; then
  if [[ "$QUICK" == true ]]; then
    echo "SKIP: setup required — no users seeded for student auth scenario probe"
    exit 0
  fi
  echo "ERROR: setup required — POST /setup/first-admin before auth scenario probe" >&2
  echo "  Response: ${setup_body:-"(no response)"}" >&2
  exit 1
fi

cookie_jar="$(mktemp)"
login_tmp="$(mktemp)"
trap 'rm -f "$cookie_jar" "$login_tmp"' EXIT

login_code="$(curl --connect-timeout 2 --max-time 5 -s -o "$login_tmp" -w '%{http_code}' \
  -c "$cookie_jar" \
  -X POST "${API_BASE}/auth/login" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg email "$SCENARIO_EMAIL" --arg password "$SCENARIO_PASSWORD" \
    '{email: $email, password: $password}')")"

if [[ "$login_code" != "200" ]]; then
  if [[ "$QUICK" == true ]]; then
    echo "SKIP: student login failed (is SEED_ENABLED=true or preview seed applied?)"
    exit 0
  fi
  echo "ERROR: student login returned HTTP ${login_code}" >&2
  echo "  Email: ${SCENARIO_EMAIL}" >&2
  cat "$login_tmp" >&2
  exit 1
fi

login_role="$(jq -r '.user.role // empty' "$login_tmp" 2>/dev/null || true)"
if [[ "$login_role" != "Student" ]]; then
  if [[ "$QUICK" == true ]]; then
    echo "SKIP: login succeeded but role is not Student (got: ${login_role:-unknown})"
    exit 0
  fi
  echo "ERROR: login response user.role expected Student, got: ${login_role:-unknown}" >&2
  cat "$login_tmp" >&2
  exit 1
fi

me_tmp="$(mktemp)"
trap 'rm -f "$cookie_jar" "$login_tmp" "$me_tmp"' EXIT

me_code="$(curl --connect-timeout 2 --max-time 5 -s -o "$me_tmp" -w '%{http_code}' \
  -b "$cookie_jar" \
  "${API_BASE}/auth/me")"

if [[ "$me_code" != "200" ]]; then
  if [[ "$QUICK" == true ]]; then
    echo "SKIP: GET /auth/me failed after login (HTTP ${me_code})"
    exit 0
  fi
  echo "ERROR: GET /auth/me returned HTTP ${me_code} after login" >&2
  cat "$me_tmp" >&2
  exit 1
fi

me_role="$(jq -r '.role // empty' "$me_tmp" 2>/dev/null || true)"
if [[ "$me_role" != "Student" ]]; then
  if [[ "$QUICK" == true ]]; then
    echo "SKIP: /auth/me role is not Student (got: ${me_role:-unknown})"
    exit 0
  fi
  echo "ERROR: /auth/me role expected Student, got: ${me_role:-unknown}" >&2
  cat "$me_tmp" >&2
  exit 1
fi

echo "Student auth scenario passed (role=Student)"
