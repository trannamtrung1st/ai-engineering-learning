#!/usr/bin/env bash
# Playwright UI regression gate (headless) — runs after browser tester codegen
# Usage: run-playwright-check.sh [sliceId]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
exec ./ai-harness/scripts/run-checks.sh "${1:-}" --playwright-only
