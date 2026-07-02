#!/usr/bin/env bash
# Portable spec generator entry point
# Usage: generate.sh [--apply] [--force] [--once]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

APPLY=false
FORCE=false
ONCE=false

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=true ;;
    --force) FORCE=true ;;
    --once) ONCE=true ;;
    -h|--help)
      cat <<EOF
Portable Spec Generator

Usage: generate.sh [--apply] [--force] [--once]

  --apply   Write docs/ and ai-harness/ to repo root (required for output)
  --force   Overwrite existing ai-harness/whole-app-backlog.json
  --once    Run a single step instead of the full loop

Fresh repo needs only:
  generator/
  docs/initial-idea.md

Environment:
  GEN_APPLY=1       Same as --apply
  GEN_FORCE=1       Same as --force
  GEN_SKIP_AGENT=1  Skip Cursor agent (testing)
  GEN_SKIP_REVIEW=1 Skip optional doc review
  GEN_MODEL=...     Override default model

After GEN_COMPLETE:
  npm run aih:testgen:loop && npm run aih:loop
EOF
      exit 0
      ;;
  esac
done

[[ "$APPLY" == true ]] && export GEN_APPLY=1
[[ "$FORCE" == true ]] && export GEN_FORCE=1

require_gen_deps
cd "$REPO_ROOT"

if [[ ! -f "$INITIAL_IDEA" ]]; then
  gen_err "Missing ${INITIAL_IDEA}"
  gen_err "Create docs/initial-idea.md with your product idea before running."
  exit 1
fi

if [[ -f "${REPO_ROOT}/ai-harness/whole-app-backlog.json" && "${GEN_FORCE:-}" != "1" && "${GEN_APPLY:-}" == "1" ]]; then
  if all_steps_pass; then
    gen_err "Generator already complete and ai-harness exists. Use --force or GEN_FORCE=1 to regenerate."
    exit 1
  elif ! generator_resume_in_progress; then
    gen_err "ai-harness already exists. Use --force or GEN_FORCE=1 to overwrite, or reset generator steps to resume."
    exit 1
  fi
fi

gen_section "Portable Spec Generator" loop
print_gen_env

if [[ "${GEN_APPLY:-}" != "1" ]]; then
  gen_warn "Dry-run mode: set GEN_APPLY=1 or pass --apply to write outputs"
  gen_warn "Steps will fail at write time without GEN_APPLY"
fi

if [[ "$ONCE" == true ]]; then
  "${GEN_SCRIPTS_DIR}/gen-once.sh"
else
  "${GEN_SCRIPTS_DIR}/gen-loop.sh"
fi

status=$?
if [[ "$status" -eq 0 ]]; then
  gen_blank
  gen_ok "Generator finished. Next:"
  gen_info "  npm run aih:testgen:loop"
  gen_info "  npm run aih:loop"
fi
exit "$status"
