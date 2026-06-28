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
echo "# Harness guardrails" > "${dest}/state/guardrails.md"

cat > "${dest}/test-case-index.json" <<EOF
{
  "current": [],
  "docFingerprint": null
}
EOF

substitute_file() {
  substitute_product_placeholders "$1" "$product_name" "$slug" "$branch" "$workspace"
}

while IFS= read -r f; do
  substitute_file "$f"
done < <(find "$dest" -type f \( -name '*.md' -o -name '*.json' -o -name '*.prompt.md' \) 2>/dev/null)

find "$dest/scripts" -name '*.sh' -exec chmod +x {} \;

gen_ok "harness scaffold emitted to ai-harness/"
