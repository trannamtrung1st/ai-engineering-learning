#!/usr/bin/env bash
# Reset local dev database volumes and re-apply migrate + seed hooks.
# Usage: ./scripts/local-runtime-reset.sh [--hard]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HARD=false
if [[ "${1:-}" == "--hard" ]]; then
  HARD=true
fi

echo "==> Stopping preview stack (if running)"
npm run aih:preview:down 2>/dev/null || true

if [[ "$HARD" == true ]]; then
  echo "==> Hard reset — removing dev compose volumes"
  docker compose down -v --remove-orphans 2>/dev/null || true
else
  echo "==> Soft reset — stopping dev compose services (volumes preserved)"
  docker compose stop db redis 2>/dev/null || true
fi

echo "==> Starting dev database and cache"
docker compose up -d db redis

echo "==> Waiting for postgres health"
for _ in $(seq 1 30); do
  status="$(docker compose ps --status running --format json db 2>/dev/null | jq -r '.Health // .State // empty' 2>/dev/null || true)"
  if [[ "$status" == "healthy" || "$status" == "running" ]]; then
    break
  fi
  sleep 2
done

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/app}"

echo "==> Running migrations and seeds"
npm run db:migrate
npm run db:seed

echo "==> Local runtime reset complete"
echo "    DATABASE_URL=$DATABASE_URL"
echo "    Next: npm run aih:preview"
