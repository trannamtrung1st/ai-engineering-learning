#!/usr/bin/env bash
# Pick next pending generator step
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps
pick_next_step_id
