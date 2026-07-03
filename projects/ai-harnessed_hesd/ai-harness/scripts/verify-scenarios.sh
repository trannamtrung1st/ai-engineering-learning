#!/usr/bin/env bash
# Generic live-stack scenario probe driven by ai-harness/config/scenario-probe.json.
# Usage: verify-scenarios.sh [--quick]
# Env: AIH_SCENARIO_PROBE_CONFIG — override config path
#      AIH_PREVIEW_API_PORT — API port (default 3001)
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

QUICK=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) QUICK=true; shift ;;
    -h|--help)
      echo "Usage: verify-scenarios.sh [--quick]"
      echo "  Reads ai-harness/config/scenario-probe.json when present; otherwise SKIP."
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

require_harness_deps
require_cmd curl
require_cmd jq

PROBE_CONFIG="${AIH_SCENARIO_PROBE_CONFIG:-${REPO_ROOT}/ai-harness/config/scenario-probe.json}"

if [[ ! -f "$PROBE_CONFIG" ]]; then
  echo "SKIP: no scenario probe configured (add ai-harness/config/scenario-probe.json)"
  exit 0
fi

API_PORT="${AIH_PREVIEW_API_PORT:-3001}"
configured_base="$(jq -r '.apiBase // empty' "$PROBE_CONFIG")"
if [[ -n "$configured_base" ]]; then
  API_BASE="$configured_base"
else
  API_BASE="http://localhost:${API_PORT}/api/v1"
fi

health_url="${API_BASE%/}/health"
health_body="$(curl --connect-timeout 2 --max-time 5 -sf "$health_url" 2>/dev/null || true)"
if [[ -z "$health_body" ]]; then
  if [[ "$QUICK" == true ]]; then
    echo "SKIP: API not running (scenario probe)"
    exit 0
  fi
  echo "ERROR: API unhealthy — cannot run scenario probe" >&2
  echo "  URL: ${health_url}" >&2
  echo "  Last response: ${health_body:-"(no response)"}" >&2
  exit 1
fi

status="$(echo "$health_body" | jq -r '.status // empty' 2>/dev/null || true)"
db="$(echo "$health_body" | jq -r '.db // empty' 2>/dev/null || true)"
if [[ "$status" != "ok" || "$db" != "connected" ]]; then
  if [[ "$QUICK" == true ]]; then
    echo "SKIP: API not healthy (scenario probe)"
    exit 0
  fi
  echo "ERROR: API unhealthy — cannot run scenario probe" >&2
  echo "  URL: ${health_url}" >&2
  echo "  Last response: ${health_body}" >&2
  exit 1
fi

TOKEN=""
step_count="$(jq '.steps | length' "$PROBE_CONFIG")"
description="$(jq -r '.description // "scenario probe"' "$PROBE_CONFIG")"

for ((i = 0; i < step_count; i++)); do
  method="$(jq -r ".steps[$i].method" "$PROBE_CONFIG")"
  path="$(jq -r ".steps[$i].path" "$PROBE_CONFIG")"
  use_auth="$(jq -r ".steps[$i].auth // false" "$PROBE_CONFIG")"
  save_token="$(jq -r ".steps[$i].saveToken // false" "$PROBE_CONFIG")"
  expect_status="$(jq -r ".steps[$i].expectStatus // empty" "$PROBE_CONFIG")"
  skip_when_empty="$(jq -r ".steps[$i].skipWhenEmpty // empty" "$PROBE_CONFIG")"

  if [[ "$path" == http://* || "$path" == https://* ]]; then
    url="$path"
  elif [[ "$path" == /* ]]; then
    url="${API_BASE%/}${path}"
  else
    url="${API_BASE%/}/${path}"
  fi

  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT

  curl_args=(--connect-timeout 2 --max-time 10 -s -o "$tmp" -w '%{http_code}')
  if [[ "$use_auth" == "true" && -n "$TOKEN" ]]; then
    curl_args+=(-H "Authorization: Bearer ${TOKEN}")
  fi

  body_json="$(jq -c ".steps[$i].body // empty" "$PROBE_CONFIG")"
  if [[ -n "$body_json" && "$body_json" != "null" ]]; then
    curl_args+=(-X "$method" -H "Content-Type: application/json" -d "$body_json")
  else
    curl_args+=(-X "$method")
  fi

  http_code="$(curl "${curl_args[@]}" "$url")"

  if [[ -n "$expect_status" && "$http_code" != "$expect_status" ]]; then
    echo "ERROR: scenario probe step $((i + 1)) (${method} ${path}) returned HTTP ${http_code}, expected ${expect_status}" >&2
    cat "$tmp" >&2
    exit 1
  fi

  if [[ "$save_token" == "true" ]]; then
    TOKEN="$(jq -r '.token // empty' "$tmp" 2>/dev/null || true)"
    if [[ -z "$TOKEN" ]]; then
      echo "ERROR: scenario probe step $((i + 1)) saveToken but response missing .token" >&2
      cat "$tmp" >&2
      exit 1
    fi
  fi

  expect_json_keys="$(jq -r ".steps[$i].expectJson // {} | keys[]" "$PROBE_CONFIG" 2>/dev/null || true)"
  if [[ -n "$expect_json_keys" ]]; then
    while IFS= read -r key; do
      [[ -z "$key" ]] && continue
      expected="$(jq -r ".steps[$i].expectJson[\"${key}\"]" "$PROBE_CONFIG")"
      actual="$(jq -r --arg k "$key" '.[$k] // empty' "$tmp" 2>/dev/null || true)"
      if [[ "$actual" != "$expected" ]]; then
        echo "ERROR: scenario probe step $((i + 1)) expectJson.${key}=${expected}, got ${actual:-"(missing)"}" >&2
        cat "$tmp" >&2
        exit 1
      fi
    done <<< "$expect_json_keys"
  fi

  if [[ -n "$skip_when_empty" ]]; then
    skip_result="$(jq -r "$skip_when_empty" "$tmp" 2>/dev/null || echo "false")"
    if [[ "$skip_result" == "true" ]]; then
      echo "SKIP: scenario probe precondition not met (${description})"
      exit 0
    fi
  fi

  rm -f "$tmp"
  trap - EXIT
done

echo "Scenario probe passed (${description})"
