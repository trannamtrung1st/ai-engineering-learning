#!/usr/bin/env bash
# Remove Playwright MCP page snapshots and console logs.
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

cleanup_playwright_mcp_artifacts
echo "Playwright MCP artifact dirs:"
playwright_mcp_artifact_dirs
