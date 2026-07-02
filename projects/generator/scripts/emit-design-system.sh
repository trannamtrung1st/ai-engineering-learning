#!/usr/bin/env bash
# Emit docs/ui-ux/design-system/*.md from generic templates with placeholder substitution
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/product-meta.sh
source "$(dirname "$0")/lib/product-meta.sh"

assert_can_write_outputs

src="${TEMPLATES_DIR}/docs/ui-ux/design-system"
dest="${REPO_ROOT}/docs/ui-ux/design-system"

if [[ ! -d "$src" ]]; then
  gen_err "missing design-system templates: $src"
  exit 1
fi

product_name="$(product_meta_field productName)"
[[ -z "$product_name" ]] && product_name="Product"
slug="$(product_slug)"
branch="$(branch_prefix)"
workspace="$(workspace_name)"

mkdir -p "$dest"
rsync -a "$src/" "$dest/"

while IFS= read -r f; do
  substitute_all_product_placeholders "$f" "$product_name" "$slug" "$branch" "$workspace"
done < <(find "$dest" -type f -name '*.md' 2>/dev/null)

gen_ok "design-system modules emitted to docs/ui-ux/design-system/"
