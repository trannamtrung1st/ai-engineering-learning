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

force_design=false
[[ "${GEN_FORCE_DESIGN:-}" == "1" ]] && force_design=true
[[ "$(gen_input_mode)" == "greenfield" ]] && force_design=true

copied=0
skipped=0

while IFS= read -r tpl_file; do
  [[ -z "$tpl_file" ]] && continue
  base="$(basename "$tpl_file")"
  out="${dest}/${base}"

  if [[ -f "$out" && "$force_design" != true ]]; then
    gen_info "design-system: skip existing ${base}"
    skipped=$((skipped + 1))
    continue
  fi

  cp "$tpl_file" "$out"
  substitute_all_product_placeholders "$out" "$product_name" "$slug" "$branch" "$workspace"
  copied=$((copied + 1))
done < <(find "$src" -type f -name '*.md' 2>/dev/null | sort)

gen_ok "design-system: copied ${copied}, skipped ${skipped} existing module(s)"
