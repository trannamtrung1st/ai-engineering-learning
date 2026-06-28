#!/usr/bin/env bash
# Poll API health and web HTTP until startup succeeds or timeout.
# Usage: verify-stack.sh [--quick] [--gate] [--api-only]
#
# Modes:
#   (default)  Full poll for preview-stack startup (60s API / 120s web dev).
#   --quick    Single-shot probe; skips when services are not listening (run-checks).
#   --gate     Strict probe for browser-test gate — must pass within 30s, no skip.
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

QUICK=false
GATE=false
API_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) QUICK=true; shift ;;
    --gate) GATE=true; shift ;;
    --api-only) API_ONLY=true; shift ;;
    -h|--help)
      echo "Usage: verify-stack.sh [--quick] [--gate] [--api-only]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ "$QUICK" == true && "$GATE" == true ]]; then
  echo "ERROR: --quick and --gate are mutually exclusive" >&2
  exit 1
fi

require_harness_deps
require_cmd curl

API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
WEB_PORT="${AIH_PREVIEW_WEB_PORT:-3000}"
MODE="${AIH_PREVIEW_MODE:-dev}"
VERIFY_CURL_CONNECT_TIMEOUT_SEC="${AIH_VERIFY_CURL_CONNECT_TIMEOUT_SEC:-2}"
VERIFY_CURL_MAX_TIME_SEC="${AIH_VERIFY_CURL_MAX_TIME_SEC:-5}"
QUICK_RETRIES="${AIH_VERIFY_QUICK_RETRIES:-3}"
QUICK_RETRY_DELAY_SEC="${AIH_VERIFY_QUICK_RETRY_DELAY_SEC:-2}"
VERIFY_POLL_INTERVAL_SEC="${AIH_VERIFY_POLL_INTERVAL_SEC:-1}"
GATE_TIMEOUT_MS="${AIH_VERIFY_GATE_TIMEOUT_MS:-10000}"
VERIFY_PROGRESS_INTERVAL_SEC="${AIH_VERIFY_PROGRESS_INTERVAL_SEC:-3}"

if [[ "$GATE" == true ]]; then
  GATE_STARTED_MS=$(( $(date +%s) * 1000 ))
  GATE_DEADLINE_MS=$(( GATE_STARTED_MS + GATE_TIMEOUT_MS ))
  AIH_VERIFY_API_TIMEOUT_MS="$GATE_TIMEOUT_MS"
  AIH_VERIFY_WEB_TIMEOUT_MS="$GATE_TIMEOUT_MS"
  VERIFY_POLL_INTERVAL_SEC="${AIH_VERIFY_GATE_POLL_INTERVAL_SEC:-1}"
elif [[ -z "${AIH_VERIFY_API_TIMEOUT_MS:-}" ]]; then
  [[ "$MODE" == "full" ]] && AIH_VERIFY_API_TIMEOUT_MS=180000 || AIH_VERIFY_API_TIMEOUT_MS=60000
fi
if [[ "$GATE" != true && -z "${AIH_VERIFY_WEB_TIMEOUT_MS:-}" ]]; then
  [[ "$MODE" == "full" ]] && AIH_VERIFY_WEB_TIMEOUT_MS=180000 || AIH_VERIFY_WEB_TIMEOUT_MS=120000
fi

API_URL="http://localhost:${API_PORT}/api/v1/health"
WEB_URL="http://localhost:${WEB_PORT}/"

verify_curl() {
  curl --connect-timeout "$VERIFY_CURL_CONNECT_TIMEOUT_SEC" \
    --max-time "$VERIFY_CURL_MAX_TIME_SEC" \
    "$@"
}

api_healthy() {
  local body="$1"
  local status db
  status="$(echo "$body" | jq -r '.status // empty' 2>/dev/null || true)"
  db="$(echo "$body" | jq -r '.db // empty' 2>/dev/null || true)"
  [[ "$status" == "ok" && "$db" == "connected" ]]
}

fetch_api_health() {
  verify_curl -sf "$API_URL" 2>/dev/null || true
}

fetch_web_status() {
  local code
  code="$(verify_curl -s -o /dev/null -w '%{http_code}' "$WEB_URL" 2>/dev/null || true)"
  [[ -n "$code" ]] && echo "$code" || echo "000"
}

poll_api() {
  local attempt=1
  local max_attempts=1
  local started_ms=$(( $(date +%s) * 1000 ))
  local deadline
  if [[ "$GATE" == true ]]; then
    deadline="$GATE_DEADLINE_MS"
  else
    deadline=$(( started_ms + AIH_VERIFY_API_TIMEOUT_MS ))
  fi
  local body last_progress_sec=-1

  if [[ "$QUICK" == true ]]; then
    max_attempts="$QUICK_RETRIES"
  fi

  while true; do
    body="$(fetch_api_health)"
    if [[ -n "$body" ]] && api_healthy "$body"; then
      echo "API healthy: $API_URL"
      return 0
    fi

    if [[ "$QUICK" == true ]]; then
      if [[ -z "$body" ]]; then
        echo "SKIP: API not running (quick probe)"
        return 0
      fi
      if (( attempt < max_attempts )); then
        sleep "$QUICK_RETRY_DELAY_SEC"
        attempt=$((attempt + 1))
        continue
      fi
      echo "ERROR: API unhealthy" >&2
      echo "  URL: $API_URL" >&2
      echo "  Last response: ${body:-"(no response)"}" >&2
      if [[ -f "$PREVIEW_API_LOG" ]]; then
        echo "  Last lines of ${PREVIEW_API_LOG}:" >&2
        tail -n 5 "$PREVIEW_API_LOG" >&2 || true
      fi
      return 1
    fi

    local now_ms=$(( $(date +%s) * 1000 ))
    if (( now_ms >= deadline )); then
      local budget_ms=$(( deadline - started_ms ))
      [[ "$GATE" == true ]] && budget_ms="$GATE_TIMEOUT_MS"
      echo "ERROR: API startup failed after ${budget_ms}ms" >&2
      echo "  URL: $API_URL" >&2
      echo "  Last response: ${body:-"(no response)"}" >&2
      if [[ "$GATE" == true && -f "$PREVIEW_API_LOG" ]]; then
        echo "  Last lines of ${PREVIEW_API_LOG}:" >&2
        tail -n 5 "$PREVIEW_API_LOG" >&2 || true
      fi
      return 1
    fi

    local elapsed_sec=$(( (now_ms - started_ms) / 1000 ))
    if [[ "$GATE" == true ]]; then
      elapsed_sec=$(( (now_ms - GATE_STARTED_MS) / 1000 ))
    fi
    if [[ "$GATE" == true ]] && (( elapsed_sec != last_progress_sec )) && (( elapsed_sec > 0 && elapsed_sec % VERIFY_PROGRESS_INTERVAL_SEC == 0 )); then
      echo "==> waiting for API health... (${elapsed_sec}s / $(( GATE_TIMEOUT_MS / 1000 ))s gate budget)" >&2
      last_progress_sec=$elapsed_sec
    fi

    sleep "$VERIFY_POLL_INTERVAL_SEC"
  done
}

poll_web() {
  local attempt=1
  local max_attempts=1
  local started_ms=$(( $(date +%s) * 1000 ))
  local deadline
  if [[ "$GATE" == true ]]; then
    deadline="$GATE_DEADLINE_MS"
  else
    deadline=$(( started_ms + AIH_VERIFY_WEB_TIMEOUT_MS ))
  fi
  local code last_progress_sec=-1

  if [[ "$QUICK" == true ]]; then
    max_attempts="$QUICK_RETRIES"
  fi

  while true; do
    code="$(fetch_web_status)"
    if [[ "$code" == "200" ]]; then
      echo "Web ready: $WEB_URL (HTTP $code)"
      return 0
    fi

    if [[ "$QUICK" == true ]]; then
      if [[ "$code" == "000" ]]; then
        echo "SKIP: Web not running (quick probe)"
        return 0
      fi
      if (( attempt < max_attempts )); then
        sleep "$QUICK_RETRY_DELAY_SEC"
        attempt=$((attempt + 1))
        continue
      fi
      echo "ERROR: Web unhealthy" >&2
      echo "  URL: $WEB_URL" >&2
      echo "  Last HTTP status: $code (after ${max_attempts} attempt(s))" >&2
      print_preview_web_hint
      return 1
    fi

    local now_ms=$(( $(date +%s) * 1000 ))
    if (( now_ms >= deadline )); then
      local budget_ms=$(( deadline - started_ms ))
      [[ "$GATE" == true ]] && budget_ms="$(( GATE_DEADLINE_MS - started_ms ))"
      echo "ERROR: Web startup failed after ${budget_ms}ms" >&2
      echo "  URL: $WEB_URL" >&2
      echo "  Last HTTP status: $code" >&2
      print_preview_web_hint
      return 1
    fi

    local elapsed_sec=$(( (now_ms - started_ms) / 1000 ))
    if [[ "$GATE" == true ]]; then
      elapsed_sec=$(( (now_ms - GATE_STARTED_MS) / 1000 ))
    fi
    if [[ "$GATE" == true ]] && (( elapsed_sec != last_progress_sec )) && (( elapsed_sec > 0 && elapsed_sec % VERIFY_PROGRESS_INTERVAL_SEC == 0 )); then
      echo "==> waiting for Web HTTP 200... (${elapsed_sec}s / $(( GATE_TIMEOUT_MS / 1000 ))s gate budget)" >&2
      last_progress_sec=$elapsed_sec
    fi

    sleep "$VERIFY_POLL_INTERVAL_SEC"
  done
}

cd "$REPO_ROOT"

if [[ "$GATE" == true ]]; then
  echo "==> Preview gate verify (strict, ${GATE_TIMEOUT_MS}ms shared budget, curl max ${VERIFY_CURL_MAX_TIME_SEC}s)" >&2
fi

poll_api
if [[ "$API_ONLY" != true ]]; then
  poll_web
fi
if [[ "$API_ONLY" == true ]]; then
  echo "Stack startup verification passed (api-only, mode=$MODE)"
elif [[ "$GATE" == true ]]; then
  echo "Stack gate verification passed (mode=$MODE, budget=${GATE_TIMEOUT_MS}ms shared)"
else
  echo "Stack startup verification passed (mode=$MODE)"
fi
