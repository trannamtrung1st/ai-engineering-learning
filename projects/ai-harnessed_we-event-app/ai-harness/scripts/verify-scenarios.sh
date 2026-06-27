#!/usr/bin/env bash
# Participant browse + registration-status scenario probe (live stack).
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
    echo "SKIP: API not running (participant scenario probe)"
    exit 0
  fi
  echo "ERROR: API unhealthy — cannot run participant scenario probe" >&2
  echo "  URL: ${API_BASE}/health" >&2
  echo "  Last response: ${health_body:-"(no response)"}" >&2
  exit 1
fi

participant_id="${AIH_PARTICIPANT_SUB:-participant-1}"
token_body="$(curl --connect-timeout 2 --max-time 5 -sf -X POST "${API_BASE}/dev/token" \
  -H "Content-Type: application/json" \
  -d "{\"sub\":\"${participant_id}\",\"role\":\"Participant\"}" 2>/dev/null || true)"

token="$(echo "$token_body" | jq -r '.token // empty' 2>/dev/null || true)"
if [[ -z "$token" ]]; then
  echo "ERROR: could not obtain participant dev token (is DEV_AUTH_ENABLED=true?)" >&2
  echo "  Response: ${token_body:-"(no response)"}" >&2
  exit 1
fi

events_body="$(curl --connect-timeout 2 --max-time 5 -sf "${API_BASE}/events?state=RegistrationOpen&pageSize=1" \
  -H "Authorization: Bearer ${token}" 2>/dev/null || true)"
event_id="$(echo "$events_body" | jq -r '.items[0].eventId // empty' 2>/dev/null || true)"

if [[ -z "$event_id" ]]; then
  echo "SKIP: no RegistrationOpen events available for participant scenario probe"
  exit 0
fi

status_tmp="$(mktemp)"
trap 'rm -f "$status_tmp"' EXIT

status_code="$(curl --connect-timeout 2 --max-time 5 -s -o "$status_tmp" -w '%{http_code}' \
  "${API_BASE}/events/${event_id}/registration-status" \
  -H "Authorization: Bearer ${token}")"

if [[ "$status_code" != "200" ]]; then
  echo "ERROR: registration-status returned HTTP ${status_code} for event ${event_id}" >&2
  cat "$status_tmp" >&2
  exit 1
fi

if ! jq -e 'has("registration")' "$status_tmp" >/dev/null 2>&1; then
  echo "ERROR: registration-status response missing registration field" >&2
  cat "$status_tmp" >&2
  exit 1
fi

existing_state="$(jq -r '.registration.state // empty' "$status_tmp" 2>/dev/null || true)"

if [[ -z "$existing_state" ]]; then
  register_tmp="$(mktemp)"
  trap 'rm -f "$status_tmp" "$register_tmp"' EXIT

  register_code="$(curl --connect-timeout 2 --max-time 5 -s -o "$register_tmp" -w '%{http_code}' \
    -X POST "${API_BASE}/events/${event_id}/registrations" \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $(uuidgen | tr '[:upper:]' '[:lower:]')" \
    -d '{}')"

  if [[ "$register_code" != "200" && "$register_code" != "201" ]]; then
    echo "ERROR: register returned HTTP ${register_code} for event ${event_id}" >&2
    cat "$register_tmp" >&2
    exit 1
  fi
else
  trap 'rm -f "$status_tmp"' EXIT
fi

after_body="$(curl --connect-timeout 2 --max-time 5 -sf "${API_BASE}/events/${event_id}/registration-status" \
  -H "Authorization: Bearer ${token}")"
registration_state="$(echo "$after_body" | jq -r '.registration.state // empty')"

if [[ -z "$registration_state" ]]; then
  echo "ERROR: registration-status after register missing registration.state" >&2
  echo "$after_body" >&2
  exit 1
fi

echo "Participant registration scenario passed (event=${event_id}, state=${registration_state})"
