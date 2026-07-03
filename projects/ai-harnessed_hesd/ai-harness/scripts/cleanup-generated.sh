#!/usr/bin/env bash
# TTL cleanup for ai-harness/generated/ run artifacts, screenshots, and evidence.
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

cleanup_generated_artifacts
