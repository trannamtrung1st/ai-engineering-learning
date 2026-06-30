#!/usr/bin/env bash
# Emit docs/ui-ux/DESIGN.md from template or vendored design-md source
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/product-meta.sh
source "$(dirname "$0")/lib/product-meta.sh"

assert_can_write_outputs

product_name="$(product_meta_field productName)"
[[ -z "$product_name" ]] && product_name="Product"
slug="$(product_slug)"
framework="$(load_product_meta | jq -r '.designSystem.framework // "default"')"
source_url="$(load_product_meta | jq -r '.designSystem.sourceUrl // empty')"

dest="${REPO_ROOT}/docs/ui-ux/DESIGN.md"
mkdir -p "$(dirname "$dest")"

write_preamble() {
  local out="$1"
  cat > "$out" <<EOF
# ${product_name} — Design Spec

## Scope

Authoritative visual design specification for **${product_name}** workspace and application UI.

- **In scope:** authenticated app shells, data tables, forms, listing pages, empty/loading/error states
- **Out of scope:** marketing landing pages, pricing tiers, and decorative hero patterns unless a route explicitly uses them
- **Implementation:** map tokens to CSS variables in [04-design-tokens.md](./04-design-tokens.md) (§0 mapping table)
- **Precedence:** this file > [04-design-tokens.md](./04-design-tokens.md) > [01-design-overview.md](./01-design-overview.md)
- **Framework:** ${framework}

Customize this preamble during the \`uiux-design-md\` step — map product routes and surfaces to components below.

---

EOF
}

if [[ -n "$source_url" ]]; then
  tmp="$(mktemp)"
  write_preamble "$tmp"
  if ! curl -fsSL "$source_url" >> "$tmp"; then
    gen_err "failed to fetch design spec: $source_url"
    rm -f "$tmp"
    exit 1
  fi
  mv "$tmp" "$dest"
  gen_ok "DESIGN.md vendored from ${source_url}"
elif [[ "$framework" != "default" ]]; then
  gen_err "designSystem.framework=${framework} requires designSystem.sourceUrl in product-meta.json"
  exit 1
else
  tpl="${TEMPLATES_DIR}/docs/ui-ux/DESIGN.md.tpl"
  if [[ ! -f "$tpl" ]]; then
    gen_err "missing template: $tpl"
    exit 1
  fi
  pn="$(sed_escape_replacement "$product_name")"
  ps="$(sed_escape_replacement "$slug")"
  sed \
    -e "s|{{PRODUCT_NAME}}|${pn}|g" \
    -e "s|{{PRODUCT_SLUG}}|${ps}|g" \
    "$tpl" > "$dest"
  gen_ok "DESIGN.md emitted from default template"
fi
