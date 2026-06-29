#!/usr/bin/env bash
# Customize harness agent prompts and README with product metadata
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/product-meta.sh
source "$(dirname "$0")/lib/product-meta.sh"

assert_can_write_outputs

product_name="$(product_meta_field productName)"
[[ -z "$product_name" ]] && product_name="Product"
slug="$(product_slug)"
branch="$(branch_prefix)"

for f in \
  "${REPO_ROOT}/ai-harness/agents/implementer.prompt.md" \
  "${REPO_ROOT}/ai-harness/agents/reviewer.prompt.md" \
  "${REPO_ROOT}/ai-harness/agents/tester.prompt.md" \
  "${REPO_ROOT}/ai-harness/agents/testgen.prompt.md" \
  "${REPO_ROOT}/ai-harness/README.md"
do
  customize_harness_agent_file "$f" "$product_name" "$slug" "$branch"
done

gen_ok "harness agents customized for ${product_name}"
