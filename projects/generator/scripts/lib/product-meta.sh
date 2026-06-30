#!/usr/bin/env bash
# Product metadata helpers for generator steps.

product_meta_file() {
  echo "${PRODUCT_META_FILE}"
}

load_product_meta() {
  local f
  f="$(product_meta_file)"
  if [[ ! -f "$f" ]]; then
    echo "{}"
    return
  fi
  cat "$f"
}

product_meta_field() {
  local field="$1"
  load_product_meta | jq -r --arg f "$field" '.[$f] // empty'
}

product_slug() {
  local name
  name="$(product_meta_field productName)"
  if [[ -z "$name" ]]; then
    echo "product"
    return
  fi
  echo "$name" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-|-$//g'
}

branch_prefix() {
  local from_meta
  from_meta="$(product_meta_field branchPrefix)"
  if [[ -n "$from_meta" ]]; then
    echo "$from_meta"
    return
  fi
  echo "aih/$(product_slug)-mvp"
}

workspace_name() {
  local slug
  slug="$(product_slug)"
  echo "@${slug}/"
}

# Escape replacement text for sed when using | as delimiter.
sed_escape_replacement() {
  printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'
}

substitute_product_placeholders() {
  local f="$1"
  local product_name="$2"
  local slug="$3"
  local branch="$4"
  local workspace="$5"
  [[ -f "$f" ]] || return 0
  if ! grep -q '{{PRODUCT_NAME}}\|{{BRANCH_PREFIX}}\|{{WORKSPACE_NAME}}\|{{PRODUCT_SLUG}}' "$f" 2>/dev/null; then
    return 0
  fi
  local tmp pn ps br ws
  tmp="$(mktemp)"
  pn="$(sed_escape_replacement "$product_name")"
  ps="$(sed_escape_replacement "$slug")"
  br="$(sed_escape_replacement "$branch")"
  ws="$(sed_escape_replacement "$workspace")"
  sed \
    -e "s|{{PRODUCT_NAME}}|${pn}|g" \
    -e "s|{{BRANCH_PREFIX}}|${br}|g" \
    -e "s|{{WORKSPACE_NAME}}|${ws}|g" \
    -e "s|{{PRODUCT_SLUG}}|${ps}|g" \
    "$f" > "$tmp"
  mv "$tmp" "$f"
}
