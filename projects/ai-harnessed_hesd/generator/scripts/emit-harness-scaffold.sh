#!/usr/bin/env bash
# Copy static ai-harness templates to repo root with placeholder substitution
# Usage: emit-harness-scaffold.sh [--verify]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
# shellcheck source=lib/product-meta.sh
source "$(dirname "$0")/lib/product-meta.sh"

VERIFY_ONLY=false
if [[ "${1:-}" == "--verify" ]]; then
  VERIFY_ONLY=true
fi

src="${TEMPLATES_DIR}/ai-harness"
dest="${REPO_ROOT}/ai-harness"

if [[ ! -d "$src" ]]; then
  gen_err "missing templates: $src"
  exit 1
fi

if [[ "$VERIFY_ONLY" == true ]]; then
  if [[ ! -d "$dest/scripts" ]]; then
    gen_err "ai-harness not scaffolded"
    exit 1
  fi
  for sh in "$dest/scripts"/*.sh; do
    [[ -f "$sh" ]] || continue
    if [[ ! -x "$sh" ]]; then
      gen_err "not executable: $sh"
      exit 1
    fi
  done
  harness_console="${dest}/scripts/lib/console.sh"
  if [[ ! -f "$harness_console" ]]; then
    gen_err "missing harness console: $harness_console"
    exit 1
  fi
  if ! grep -q '^aih_step()' "$harness_console" 2>/dev/null; then
    gen_err "harness console must define aih_step() — found generator console (gen_*)?"
    exit 1
  fi
  gen_ok "harness-scaffold verified"
  exit 0
fi

assert_safe_to_scaffold_harness

product_name="$(product_meta_field productName)"
[[ -z "$product_name" ]] && product_name="Product"
slug="$(product_slug)"
branch="$(branch_prefix)"
workspace="@${slug}/"

mkdir -p "$dest"

rsync -a \
  --exclude='generated/' \
  --exclude='whole-app-backlog.json' \
  --exclude='test-case-index.json' \
  --exclude='state/progress.md' \
  --exclude='state/guardrails.md' \
  "$src/" "$dest/"

mkdir -p "$dest/generated/runs" "$dest/state"
echo "# Harness progress" > "${dest}/state/progress.md"
cat > "${dest}/state/guardrails.md" <<'EOF'
# Harness guardrails

Verification failures and remediation notes for harness agents.

## Doc requirements

- **Listing pages:** Collection views must implement search, filter, sort, and pagination per [14-listing-pages-search-filter-sort.md](../docs/ui-ux/14-listing-pages-search-filter-sort.md) §0 (documented UX variants allowed). Apply `TableToolbar` and listing chrome per [design-system/tables.md](../../docs/ui-ux/design-system/tables.md).
- **Design craft:** Visual implementation via [`visual-design`](../skills/visual-design/SKILL.md) and [design-system/](../../docs/ui-ux/design-system/) modules. Authoritative index [DESIGN.md](../../docs/ui-ux/DESIGN.md); product tokens in [04-design-tokens.md](../../docs/ui-ux/04-design-tokens.md) always win for CSS values.
- **Table toolbar:** Listing routes use `TableToolbar` per [05-common-ui-components.md](../../docs/ui-ux/05-common-ui-components.md).

## Signs

EOF

cat > "${dest}/test-case-index.json" <<EOF
{
  "current": [],
  "docFingerprint": null
}
EOF

substitute_file() {
  substitute_all_product_placeholders "$1" "$product_name" "$slug" "$branch" "$workspace"
}

while IFS= read -r f; do
  substitute_file "$f"
done < <(find "$dest" -type f \( -name '*.md' -o -name '*.json' -o -name '*.prompt.md' -o -name '*.sh' \) 2>/dev/null)

find "$dest/scripts" -name '*.sh' -exec chmod +x {} \;

pw_src="${TEMPLATES_DIR}/tests/playwright-ui"
pw_dest="${REPO_ROOT}/tests/playwright-ui"
if [[ -d "$pw_src" ]]; then
  mkdir -p "$pw_dest"
  rsync -a "$pw_src/" "$pw_dest/"
  while IFS= read -r f; do
    substitute_file "$f"
  done < <(find "$pw_dest" -type f \( -name '*.json' -o -name '*.ts' \) 2>/dev/null)
fi

gen_ok "harness scaffold emitted to ai-harness/"
