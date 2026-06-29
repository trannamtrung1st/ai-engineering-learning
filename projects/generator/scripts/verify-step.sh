#!/usr/bin/env bash
# Dispatch validators for a generator step
# Usage: verify-step.sh <stepId>
#        verify-step.sh --all-passed
#        verify-step.sh --dry-run <stepId>
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
require_gen_deps

if [[ "${1:-}" == "--all-passed" ]]; then
  if all_steps_pass; then
    gen_ok "All generator steps passed"
    echo "GEN_COMPLETE"
    exit 0
  fi
  gen_err "Pending steps remain"
  jq -r '.steps[] | select(.passes == false) | .id' "$STEPS_BACKLOG"
  exit 1
fi

STEP_ID="${1:?step id required}"
DRY_RUN=false
if [[ "$STEP_ID" == "--dry-run" ]]; then
  DRY_RUN=true
  STEP_ID="${2:?step id required after --dry-run}"
fi

if [[ "$DRY_RUN" == true ]]; then
  GEN_APPLY=1
fi

fail=0
scripts_dir="$(dirname "$0")"

run_validator() {
  local vid="$1"
  gen_step "Validator: $vid"
  set +e
  case "$vid" in
    input-meta)
      meta="$(product_meta_file)"
      if [[ ! -f "$meta" ]]; then
        gen_err "product-meta.json missing at docs/product-meta.json"
        fail=1
      elif [[ $(wc -c < "$meta" | tr -d ' ') -lt 20 ]]; then
        gen_err "product-meta.json too small"
        fail=1
      else
        gen_ok "input-meta ok"
      fi
      ;;
    product-meta-schema)
      meta="$(product_meta_file)"
      if [[ -f "$meta" ]]; then
        pn="$(jq -r '.productName // empty' "$meta")"
        if [[ -z "$pn" || ${#pn} -lt 2 ]]; then
          gen_err "productName missing or too short"
          fail=1
        else
          gen_ok "product-meta-schema ok"
        fi
      else
        fail=1
      fi
      ;;
    outputs-exist)
      while IFS= read -r out; do
        [[ -z "$out" ]] && continue
        abs="$(resolve_repo_path "$out")"
        if [[ ! -f "$abs" && ! -d "$abs" ]]; then
          gen_err "missing output: $out"
          fail=1
        fi
      done < <(step_outputs "$STEP_ID")
      [[ "$fail" -eq 0 ]] && gen_ok "outputs-exist ok"
      ;;
    doc-structure)
      "$scripts_dir/verify-doc-structure.sh" $(step_outputs "$STEP_ID") || fail=1
      ;;
    requirement-ids)
      "$scripts_dir/verify-requirement-ids.sh" $(step_outputs "$STEP_ID") || fail=1
      ;;
    requirement-ids-global)
      "$scripts_dir/verify-requirement-ids.sh" --global || fail=1
      ;;
    placeholder-scan)
      while IFS= read -r out; do
        [[ -z "$out" ]] && continue
        abs="$(resolve_repo_path "$out")"
        [[ -f "$abs" ]] || continue
        while IFS= read -r pat; do
          [[ -z "$pat" ]] && continue
          if grep -qi "$pat" "$abs" 2>/dev/null; then
            gen_err "$out: forbidden placeholder: $pat"
            fail=1
          fi
        done < <(jq -r '.placeholderPatterns[]?' "$LOOP_CONFIG")
      done < <(step_outputs "$STEP_ID")
      [[ "$fail" -eq 0 ]] && gen_ok "placeholder-scan ok"
      ;;
    crossrefs)
      roots="docs/brds"
      allow_missing=()
      case "$STEP_ID" in
        brd-consistency-gate)
          # BRDs may name later-phase doc trees before those steps run.
          allow_missing=(docs/ui-ux docs/technical ai-harness)
          ;;
        tech-consistency-gate)
          roots="docs/technical"
          allow_missing=(docs/ui-ux docs/test-reports ai-harness)
          ;;
        uiux-consistency-gate)
          roots="docs/ui-ux"
          allow_missing=(ai-harness)
          ;;
        harness-context-maps)
          roots="ai-harness/config docs/brds docs/technical"
          allow_missing=(docs/ui-ux docs/test-reports ai-harness)
          ;;
      esac
      if [[ ${#allow_missing[@]} -gt 0 ]]; then
        "$scripts_dir/verify-crossrefs.sh" --allow-missing "${allow_missing[@]}" -- $roots || fail=1
      else
        "$scripts_dir/verify-crossrefs.sh" $roots || fail=1
      fi
      ;;
    brd-consistency)
      "$scripts_dir/verify-requirement-ids.sh" --global || fail=1
      ;;
    tech-consistency)
      fr_file="$(resolve_repo_path docs/brds/03-functional-requirements.md)"
      api_file="$(resolve_repo_path docs/technical/05-api-design.md)"
      if [[ -f "$fr_file" && -f "$api_file" ]]; then
        missing=0
        while IFS= read -r fr; do
          [[ -z "$fr" ]] && continue
          if ! grep -q "$fr" "$api_file" 2>/dev/null; then
            gen_warn "FR $fr not referenced in API design (non-fatal)"
          fi
        done < <(grep -oE 'FR-[0-9]{2}' "$fr_file" | head -5)
        gen_ok "tech-consistency checked"
      else
        gen_err "missing FR or API docs"
        fail=1
      fi
      ;;
    uiux-consistency)
      ac_file="$(resolve_repo_path docs/brds/08-acceptance-mvp-future.md)"
      flows_file="$(resolve_repo_path docs/ui-ux/10-user-flows.md)"
      if [[ -f "$ac_file" && -f "$flows_file" ]]; then
        missing=0
        while IFS= read -r ac; do
          [[ -z "$ac" ]] && continue
          if ! grep -q "$ac" "$flows_file" 2>/dev/null; then
            missing=$((missing + 1))
          fi
        done < <(grep -oE 'AC-[0-9]{2}' "$ac_file" | head -10)
        if [[ "$missing" -gt 5 ]]; then
          gen_err "too many AC tags missing from user flows ($missing)"
          fail=1
        else
          gen_ok "uiux-consistency ok"
        fi
      else
        gen_err "missing AC or flows docs"
        fail=1
      fi
      ;;
    harness-scaffold)
      "$scripts_dir/emit-harness-scaffold.sh" --verify || fail=1
      ;;
    harness-backlog-schema)
      bl="$(resolve_repo_path ai-harness/whole-app-backlog.json)"
      if [[ ! -f "$bl" ]]; then fail=1; else gen_ok "harness-backlog exists"; fi
      ;;
    harness-backlog-tags)
      "$scripts_dir/verify-harness-config.sh" || fail=1
      ;;
    harness-context-maps)
      "$scripts_dir/verify-harness-config.sh" || fail=1
      ;;
    harness-customize)
      impl="$(resolve_repo_path ai-harness/agents/implementer.prompt.md)"
      unresolved=0
      for ph in '{{PRODUCT_NAME}}' '{{BRANCH_PREFIX}}' '{{WORKSPACE_NAME}}' '{{PRODUCT_SLUG}}'; do
        if [[ -f "$impl" ]] && grep -qF "$ph" "$impl" 2>/dev/null; then
          gen_err "implementer prompt still has ${ph}"
          unresolved=1
        fi
      done
      if [[ "$unresolved" -eq 0 ]]; then
        gen_ok "harness-customize ok"
      else
        fail=1
      fi
      ;;
    placeholder-scan-harness)
      # Agent prompts keep runtime tokens (e.g. {{SLICE_ID}}) filled by ai-harness build-prompt.sh.
      gen_placeholders=('{{PRODUCT_NAME}}' '{{BRANCH_PREFIX}}' '{{WORKSPACE_NAME}}' '{{PRODUCT_SLUG}}')
      while IFS= read -r out; do
        [[ -z "$out" ]] && continue
        abs="$(resolve_repo_path "$out")"
        [[ -f "$abs" ]] || continue
        for ph in "${gen_placeholders[@]}"; do
          if grep -qF "$ph" "$abs" 2>/dev/null; then
            gen_err "$out: unresolved generator placeholder: ${ph}"
            fail=1
          fi
        done
      done < <(step_outputs "$STEP_ID")
      [[ "$fail" -eq 0 ]] && gen_ok "placeholder-scan-harness ok"
      ;;
    repo-bootstrap)
      if [[ ! -f "${REPO_ROOT}/package.json" ]]; then
        gen_err "package.json missing"
        fail=1
      elif ! grep -q 'aih:once' "${REPO_ROOT}/package.json" 2>/dev/null; then
        gen_err "package.json missing aih:once script"
        fail=1
      elif grep -qE 'gen:(once|loop|verify)|generator/' "${REPO_ROOT}/package.json" 2>/dev/null; then
        gen_err "package.json must not reference generator"
        fail=1
      else
        gen_ok "repo-bootstrap ok"
      fi
      ;;
    no-generator-refs)
      case "$STEP_ID" in
        brd-consistency-gate|tech-consistency-gate|uiux-consistency-gate)
          "$scripts_dir/verify-no-generator-refs.sh" --scan-docs || fail=1
          ;;
        repo-bootstrap)
          "$scripts_dir/verify-no-generator-refs.sh" --scan-docs || fail=1
          ;;
        *)
          paths=()
          while IFS= read -r out; do
            [[ -z "$out" ]] && continue
            paths+=("$out")
          done < <(step_outputs "$STEP_ID")
          if [[ ${#paths[@]} -gt 0 ]]; then
            "$scripts_dir/verify-no-generator-refs.sh" "${paths[@]}" || fail=1
          else
            gen_ok "no-generator-refs ok (no outputs)"
          fi
          ;;
      esac
      ;;
    *)
      gen_warn "unknown validator: $vid (skipped)"
      ;;
  esac
  set -e
}

while IFS= read -r vid; do
  [[ -z "$vid" ]] && continue
  run_validator "$vid"
done < <(step_validators "$STEP_ID")

if [[ "$fail" -ne 0 ]]; then
  gen_err "Step ${STEP_ID} verification failed"
  exit 1
fi

gen_ok "Step ${STEP_ID} verification passed"
exit 0
