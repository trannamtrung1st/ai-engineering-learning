#!/usr/bin/env bash
# View preview stack logs (combined or per-service).
# Usage: preview-logs.sh [--follow] [--lines N] [combined|stack|api|web|db|all]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

FOLLOW=false
LINES="${AIH_PREVIEW_LOG_LINES:-50}"
TARGET="combined"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --follow|-f) FOLLOW=true; shift ;;
    --lines) LINES="$2"; shift 2 ;;
    --lines=*) LINES="${1#*=}"; shift ;;
    combined|stack|api|web|db|all) TARGET="$1"; shift ;;
    -h|--help)
      cat <<EOF
Usage: preview-logs.sh [--follow] [--lines N] [combined|stack|api|web|db|all]

Log files (under ai-harness/generated/runs/):
  preview-combined.log  — all services, timestamped + tagged
  preview-stack.log     — harness orchestration (start/stop/build/verify)
  preview-api.log       — API dev process
  preview-web.log       — Web dev process
  preview-db.log        — Postgres container

Examples:
  npm run aih:preview:logs
  npm run aih:preview:logs -- --follow
  npm run aih:preview:logs -- api --lines 100
  npm run aih:preview:logs -- all --follow
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

resolve_log_files() {
  case "$TARGET" in
    combined) echo "$PREVIEW_COMBINED_LOG" ;;
    stack) echo "$PREVIEW_STACK_LOG" ;;
    api) echo "$PREVIEW_API_LOG" ;;
    web) echo "$PREVIEW_WEB_LOG" ;;
    db) echo "$PREVIEW_DB_LOG" ;;
    all) preview_log_files ;;
  esac
}

files=()
while IFS= read -r _log_path; do
  [[ -z "$_log_path" ]] && continue
  files+=("$_log_path")
done < <(resolve_log_files)

existing=()
local_missing=()
for f in "${files[@]}"; do
  if [[ -f "$f" ]]; then
    existing+=("$f")
  else
    local_missing+=("$f")
  fi
done

if [[ ${#existing[@]} -eq 0 ]]; then
  echo "No preview log files found. Start the stack with: npm run aih:preview" >&2
  if [[ ${#local_missing[@]} -gt 0 ]]; then
    echo "Expected:" >&2
    printf '  %s\n' "${local_missing[@]}" >&2
  fi
  exit 1
fi

if [[ ${#local_missing[@]} -gt 0 && "$TARGET" == "all" ]]; then
  echo "Note: some log files do not exist yet:" >&2
  printf '  %s\n' "${local_missing[@]}" >&2
fi

if [[ "$FOLLOW" == true ]]; then
  tail -n "$LINES" -f "${existing[@]}"
else
  tail -n "$LINES" "${existing[@]}"
fi
