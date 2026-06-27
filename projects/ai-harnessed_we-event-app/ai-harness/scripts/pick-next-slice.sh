#!/usr/bin/env bash
# Print the next incomplete slice id (lowest priority), or nothing if complete
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps

if all_slices_pass; then
  exit 0
fi

pick_next_slice_id
