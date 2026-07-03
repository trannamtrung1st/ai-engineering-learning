#!/usr/bin/env bash
# Scan docs/ and emit state/docs-inventory.json
# Usage: discover-docs.sh [--summary]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

discover_docs

if [[ "${1:-}" == "--summary" ]]; then
  docs_inventory_summary
else
  gen_ok "docs inventory written to ${DOCS_INVENTORY}"
  jq -r '"seed=\(.seedPaths | length) designSystem=\(.hasDesignSystem) phase0=\(.completeness.phase0)"' "$DOCS_INVENTORY"
fi
