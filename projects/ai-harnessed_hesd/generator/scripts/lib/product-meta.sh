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

primary_actor() {
  load_product_meta | jq -r '.actors[0] // empty'
}

secondary_actor() {
  load_product_meta | jq -r '.actors[1] // empty'
}

design_style_name() {
  load_product_meta | jq -r '.designSystem.styleName // "neutral workspace"'
}

design_primary_color() {
  load_product_meta | jq -r '.designSystem.primaryColor // "#2563eb"'
}

design_border_style() {
  load_product_meta | jq -r '.designSystem.borderStyle // "1px solid var(--hairline)"'
}

design_radius_default() {
  load_product_meta | jq -r '.designSystem.radiusDefault // "6px"'
}

design_shadow_style() {
  load_product_meta | jq -r '.designSystem.shadowStyle // "soft elevation (tokenized card and dropdown shadows)"'
}

design_heading_font() {
  load_product_meta | jq -r '.designSystem.headingFont // "Inter, system-ui, sans-serif"'
}

design_body_font() {
  load_product_meta | jq -r '.designSystem.bodyFont // "Inter, system-ui, sans-serif"'
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
  if ! grep -qE '{{PRODUCT_NAME}}|{{BRANCH_PREFIX}}|{{WORKSPACE_NAME}}|{{PRODUCT_SLUG}}|{{PRIMARY_ACTOR}}|{{SECONDARY_ACTOR}}' "$f" 2>/dev/null; then
    return 0
  fi
  local tmp pn ps br ws pa sa
  tmp="$(mktemp)"
  pn="$(sed_escape_replacement "$product_name")"
  ps="$(sed_escape_replacement "$slug")"
  br="$(sed_escape_replacement "$branch")"
  ws="$(sed_escape_replacement "$workspace")"
  pa="$(sed_escape_replacement "$(primary_actor)")"
  sa="$(sed_escape_replacement "$(secondary_actor)")"
  sed \
    -e "s|{{PRODUCT_NAME}}|${pn}|g" \
    -e "s|{{BRANCH_PREFIX}}|${br}|g" \
    -e "s|{{WORKSPACE_NAME}}|${ws}|g" \
    -e "s|{{PRODUCT_SLUG}}|${ps}|g" \
    -e "s|{{PRIMARY_ACTOR}}|${pa}|g" \
    -e "s|{{SECONDARY_ACTOR}}|${sa}|g" \
    "$f" > "$tmp"
  mv "$tmp" "$f"
}

substitute_design_placeholders() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  if ! grep -qE '{{DESIGN_STYLE_NAME}}|{{PRIMARY_COLOR}}|{{BORDER_STYLE}}|{{RADIUS_DEFAULT}}|{{SHADOW_STYLE}}|{{HEADING_FONT}}|{{BODY_FONT}}' "$f" 2>/dev/null; then
    return 0
  fi
  local tmp dsn pc bs rd ss hf bf
  tmp="$(mktemp)"
  dsn="$(sed_escape_replacement "$(design_style_name)")"
  pc="$(sed_escape_replacement "$(design_primary_color)")"
  bs="$(sed_escape_replacement "$(design_border_style)")"
  rd="$(sed_escape_replacement "$(design_radius_default)")"
  ss="$(sed_escape_replacement "$(design_shadow_style)")"
  hf="$(sed_escape_replacement "$(design_heading_font)")"
  bf="$(sed_escape_replacement "$(design_body_font)")"
  sed \
    -e "s|{{DESIGN_STYLE_NAME}}|${dsn}|g" \
    -e "s|{{PRIMARY_COLOR}}|${pc}|g" \
    -e "s|{{BORDER_STYLE}}|${bs}|g" \
    -e "s|{{RADIUS_DEFAULT}}|${rd}|g" \
    -e "s|{{SHADOW_STYLE}}|${ss}|g" \
    -e "s|{{HEADING_FONT}}|${hf}|g" \
    -e "s|{{BODY_FONT}}|${bf}|g" \
    "$f" > "$tmp"
  mv "$tmp" "$f"
}

substitute_all_product_placeholders() {
  local f="$1"
  local product_name="$2"
  local slug="$3"
  local branch="$4"
  local workspace="$5"
  substitute_product_placeholders "$f" "$product_name" "$slug" "$branch" "$workspace"
  substitute_design_placeholders "$f"
}
