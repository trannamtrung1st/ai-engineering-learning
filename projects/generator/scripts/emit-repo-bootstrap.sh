#!/usr/bin/env bash
# Emit root package.json, .gitignore, .env.example from templates
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/product-meta.sh
source "$(dirname "$0")/lib/product-meta.sh"

assert_can_write_outputs

product_name="$(product_meta_field productName)"
slug="$(product_slug)"
[[ -z "$product_name" ]] && product_name="Product"

desc="${product_name} MVP — npm workspaces monorepo (apps/api, apps/web, packages/domain, packages/config)"

cat > "${REPO_ROOT}/package.json" <<EOF
{
  "name": "${slug}",
  "version": "0.1.0",
  "private": true,
  "description": "${desc}",
  "workspaces": [
    "apps/*",
    "packages/*",
    "tests/*"
  ],
  "engines": {
    "node": ">=20"
  },
  "scripts": {
    "typecheck": "npm run typecheck -ws --if-present",
    "lint": "npm run lint -ws --if-present",
    "build": "npm run build -ws --if-present",
    "test:unit": "npm run test:unit -ws --if-present",
    "test:integration": "npm run test:integration -ws --if-present",
    "test:e2e": "npm run test:e2e -w @${slug}/e2e --if-present",
    "test": "npm run test:unit && npm run test:integration && npm run test:e2e",
    "aih:once": "./ai-harness/scripts/ralph-once.sh",
    "aih:loop": "./ai-harness/scripts/ralph-loop.sh",
    "aih:loop:bg": "./ai-harness/scripts/ralph-loop-daemon.sh",
    "aih:loop:stop": "./ai-harness/scripts/ralph-loop-stop.sh",
    "aih:check": "./ai-harness/scripts/run-checks.sh",
    "aih:browser-test": "./ai-harness/scripts/run-browser-test.sh",
    "aih:review": "./ai-harness/scripts/run-ai-review.sh",
    "aih:dev:db:up": "docker compose up -d db",
    "aih:dev:db:down": "docker compose stop db",
    "aih:preview": "./ai-harness/scripts/preview-stack.sh --mode dev",
    "aih:preview:full": "./ai-harness/scripts/preview-stack.sh --mode full",
    "aih:preview:down": "./ai-harness/scripts/preview-stack.sh --down",
    "aih:preview:verify": "./ai-harness/scripts/verify-stack.sh",
    "aih:preview:scenarios": "./ai-harness/scripts/verify-scenarios.sh",
    "aih:preview:logs": "./ai-harness/scripts/preview-logs.sh",
    "aih:playwright-mcp:clean": "./ai-harness/scripts/cleanup-playwright-mcp.sh",
    "aih:testgen:once": "./ai-harness/scripts/testgen-once.sh",
    "aih:testgen:loop": "./ai-harness/scripts/testgen-loop.sh",
    "aih:testgen:enhance": "./ai-harness/scripts/testgen-enhance.sh",
    "aih:testgen:drift": "./ai-harness/scripts/check-test-case-drift.sh",
    "aih:testgen:validate": "./ai-harness/scripts/validate-test-cases.sh",
    "aih:testgen:audit": "./ai-harness/scripts/audit-test-coverage.sh"
  }
}
EOF

if [[ ! -f "${REPO_ROOT}/.gitignore" ]] || [[ "${GEN_FORCE:-}" == "1" ]]; then
  cat > "${REPO_ROOT}/.gitignore" <<'EOF'
.env
node_modules/
.npm-cache/
ai-harness/generated/runs/
.playwright-mcp/
*.log
dist/
.next/
*.tsbuildinfo
EOF
fi

if [[ ! -f "${REPO_ROOT}/.env.example" ]]; then
  cat > "${REPO_ROOT}/.env.example" <<'EOF'
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/app
API_PORT=3001
WEB_PORT=3000
EOF
fi

gen_ok "repo bootstrap files emitted"
