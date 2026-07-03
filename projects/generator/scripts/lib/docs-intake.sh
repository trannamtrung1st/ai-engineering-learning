#!/usr/bin/env bash
# Docs folder discovery and flexible intake helpers.
# Sourced from lib/common.sh after REPO_ROOT and GEN_STATE_DIR are set.

DOCS_INVENTORY="${GEN_STATE_DIR}/docs-inventory.json"
DOCS_DIR="${REPO_ROOT}/docs"

gen_input_mode() {
  if [[ -n "${GEN_INPUT_MODE:-}" ]]; then
    echo "$GEN_INPUT_MODE"
    return
  fi
  if [[ -f "$LOOP_CONFIG" ]]; then
    local mode
    mode="$(jq -r '.inputMode // "flexible"' "$LOOP_CONFIG" 2>/dev/null || echo flexible)"
    if [[ "$mode" == "greenfield" || "$mode" == "flexible" ]]; then
      echo "$mode"
      return
    fi
  fi
  echo "flexible"
}

classify_doc_zone() {
  local rel="$1"
  case "$rel" in
    docs/test-cases/*) echo "skip" ;;
    docs/initial-idea.md) echo "seed" ;;
    docs/product-meta.json) echo "meta" ;;
    docs/brds/*) echo "brds" ;;
    docs/technical/*) echo "technical" ;;
    docs/ui-ux/design-system/*) echo "designSystem" ;;
    docs/ui-ux/DESIGN.md) echo "designSystem" ;;
    docs/ui-ux/*) echo "uiux" ;;
    docs/*.md) echo "seed" ;;
    docs/*) echo "misc" ;;
    *) echo "misc" ;;
  esac
}

is_seed_path() {
  local rel="$1"
  local zone
  zone="$(classify_doc_zone "$rel")"
  case "$zone" in
    seed|brds|designSystem) return 0 ;;
    meta)
      [[ "$rel" == "docs/product-meta.json" ]] && return 0
      ;;
  esac
  [[ "$rel" == docs/*.md ]] && return 0
  return 1
}

file_has_requirement_ids() {
  local abs="$1"
  grep -qE '(FR|BR|AC|NFR)-[0-9]{2}' "$abs" 2>/dev/null
}

file_outline_key() {
  local rel="$1"
  if jq -e --arg p "$rel" '.[$p]' "$DOC_OUTLINES" >/dev/null 2>&1; then
    echo "$rel"
  else
    echo ""
  fi
}

valid_product_meta() {
  local meta="${REPO_ROOT}/docs/product-meta.json"
  [[ -f "$meta" ]] || return 1
  local pn pa sa
  pn="$(jq -r '.productName // empty' "$meta")"
  pa="$(jq -r '.actors[0] // empty' "$meta")"
  sa="$(jq -r '.actors[1] // empty' "$meta")"
  [[ -n "$pn" && ${#pn} -ge 2 && -n "$pa" && -n "$sa" ]]
}

discover_docs() {
  require_gen_deps
  mkdir -p "$GEN_STATE_DIR"

  local docs_root="${DOCS_DIR}"
  if [[ ! -d "$docs_root" ]]; then
  jq -n \
    --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg root "$REPO_ROOT" \
    --arg mode "$(gen_input_mode)" \
    '{
      generatedAt: $ts,
      repoRoot: $root,
      inputMode: $mode,
      zones: { seed: [], meta: [], brds: [], technical: [], uiux: [], designSystem: [], misc: [] },
      files: [],
      seedPaths: [],
      hasDesignSystem: false,
      completeness: { phase0: false, phase1: false, phase2: false, phase3: false }
    }' > "$DOCS_INVENTORY"
    return 0
  fi

  local tmp_files tmp_zones
  tmp_files="$(mktemp)"
  tmp_zones="$(mktemp)"

  : > "$tmp_files"
  printf '%s\n' '{"seed":[],"meta":[],"brds":[],"technical":[],"uiux":[],"designSystem":[],"misc":[]}' > "$tmp_zones"

  while IFS= read -r abs; do
    [[ -z "$abs" ]] && continue
    local rel="${abs#"${REPO_ROOT}/"}"
    local zone lines has_ids outline_key
    zone="$(classify_doc_zone "$rel")"
    [[ "$zone" == "skip" ]] && continue

    if [[ -f "$abs" ]]; then
      lines="$(wc -l < "$abs" | tr -d ' ')"
      has_ids=false
      file_has_requirement_ids "$abs" && has_ids=true
      outline_key="$(file_outline_key "$rel")"
      jq -n \
        --arg path "$rel" \
        --arg zone "$zone" \
        --argjson lines "$lines" \
        --argjson has_ids "$has_ids" \
        --arg outline "${outline_key:-null}" \
        '{path: $path, zone: $zone, lines: $lines, hasRequirementIds: $has_ids, outlineKey: (if $outline == "" or $outline == "null" then null else $outline end)}' \
        >> "$tmp_files"
    fi
  done < <(find "$docs_root" -type f \( -name '*.md' -o -name '*.json' \) ! -path '*/test-cases/*' 2>/dev/null | sort)

  local files_json
  if [[ -s "$tmp_files" ]]; then
    files_json="$(jq -s '.' "$tmp_files")"
  else
    files_json='[]'
  fi

  local seed_paths
  seed_paths="$(echo "$files_json" | jq -r '
    [.[] | select(
      .zone == "seed" or .zone == "brds" or .zone == "designSystem" or
      (.path == "docs/product-meta.json")
    ) | .path] | unique | .[]' 2>/dev/null || true)"

  local has_design=false
  if echo "$files_json" | jq -e '[.[] | select(.zone == "designSystem")] | length > 0' >/dev/null 2>&1; then
    has_design=true
  fi

  local phase0=false phase1=false phase2=false phase3=false
  valid_product_meta && phase0=true

  phase1_complete() {
    local missing
    missing="$(jq -r '
      [.steps[] | select(.phase == 1 and .kind != "gate") | .outputs[]?] | unique | .[]' "$STEPS_BACKLOG" | while read -r out; do
      [[ -z "$out" ]] && continue
      [[ -f "$(resolve_repo_path "$out")" ]] || echo "$out"
    done | wc -l | tr -d ' ')"
    [[ "$missing" -eq 0 ]]
  }

  phase2_complete() {
    local missing
    missing="$(jq -r '
      [.steps[] | select(.phase == 2 and .kind != "gate") | .outputs[]?] | unique | .[]' "$STEPS_BACKLOG" | while read -r out; do
      [[ -z "$out" ]] && continue
      [[ -f "$(resolve_repo_path "$out")" ]] || echo "$out"
    done | wc -l | tr -d ' ')"
    [[ "$missing" -eq 0 ]]
  }

  phase3_complete() {
    local missing
    missing="$(jq -r '
      [.steps[] | select(.phase == 3 and .kind != "gate") | .outputs[]?] | unique | .[]' "$STEPS_BACKLOG" | while read -r out; do
      [[ -z "$out" ]] && continue
      if [[ "$out" == */ ]]; then
        [[ -d "$(resolve_repo_path "$out")" ]] || echo "$out"
      else
        [[ -f "$(resolve_repo_path "$out")" ]] || echo "$out"
      fi
    done | wc -l | tr -d ' ')"
    [[ "$missing" -eq 0 ]]
  }

  phase1_complete && phase1=true
  phase2_complete && phase2=true
  phase3_complete && phase3=true

  local zones_json
  zones_json="$(echo "$files_json" | jq '
    {
      seed: [.[] | select(.zone == "seed") | .path],
      meta: [.[] | select(.zone == "meta") | .path],
      brds: [.[] | select(.zone == "brds") | .path],
      technical: [.[] | select(.zone == "technical") | .path],
      uiux: [.[] | select(.zone == "uiux") | .path],
      designSystem: [.[] | select(.zone == "designSystem") | .path],
      misc: [.[] | select(.zone == "misc") | .path]
    }
  ')"

  local seed_json='[]'
  if [[ -n "$seed_paths" ]]; then
    seed_json="$(printf '%s\n' "$seed_paths" | jq -R -s 'split("\n") | map(select(length > 0))')"
  fi

  jq -n \
    --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg root "$REPO_ROOT" \
    --arg mode "$(gen_input_mode)" \
    --argjson files "$files_json" \
    --argjson zones "$zones_json" \
    --argjson seeds "$seed_json" \
    --argjson has_design "$has_design" \
    --argjson phase0 "$phase0" \
    --argjson phase1 "$phase1" \
    --argjson phase2 "$phase2" \
    --argjson phase3 "$phase3" \
    '{
      generatedAt: $ts,
      repoRoot: $root,
      inputMode: $mode,
      zones: $zones,
      files: $files,
      seedPaths: $seeds,
      hasDesignSystem: $has_design,
      completeness: { phase0: $phase0, phase1: $phase1, phase2: $phase2, phase3: $phase3 }
    }' > "$DOCS_INVENTORY"

  rm -f "$tmp_files" "$tmp_zones"
}

has_any_seed() {
  discover_docs
  if valid_product_meta; then
    return 0
  fi
  local count
  count="$(jq -r '.seedPaths | length' "$DOCS_INVENTORY" 2>/dev/null || echo 0)"
  [[ "$count" -gt 0 ]]
}

docs_inventory_summary() {
  if [[ ! -f "$DOCS_INVENTORY" ]]; then
    discover_docs
  fi
  jq -r '
    "Input mode: \(.inputMode)",
    "Seed docs: \(.seedPaths | length)",
    "Design system present: \(.hasDesignSystem)",
    "Completeness: phase0=\(.completeness.phase0) phase1=\(.completeness.phase1) phase2=\(.completeness.phase2) phase3=\(.completeness.phase3)",
    "Zones: brds=\(.zones.brds | length) technical=\(.zones.technical | length) uiux=\(.zones.uiux | length) designSystem=\(.zones.designSystem | length)"
  ' "$DOCS_INVENTORY"
}

seed_docs_list() {
  if [[ ! -f "$DOCS_INVENTORY" ]]; then
    discover_docs
  fi
  jq -r '.seedPaths[]?' "$DOCS_INVENTORY"
}

phase_zone_for_step() {
  local step_id="$1"
  local phase
  phase="$(get_step_field "$step_id" phase)"
  case "$phase" in
    0) echo "seed meta" ;;
    1) echo "seed brds meta" ;;
    2) echo "brds technical meta" ;;
    3) echo "uiux designSystem brds technical meta" ;;
    4|5) echo "brds technical uiux designSystem meta" ;;
    *) echo "seed brds technical uiux designSystem meta misc" ;;
  esac
}

step_relevant_docs() {
  local step_id="$1"
  local max_docs="${2:-30}"

  if [[ ! -f "$DOCS_INVENTORY" ]]; then
    discover_docs
  fi

  local zones
  zones="$(phase_zone_for_step "$step_id")"
  local zone_filter
  zone_filter="$(printf '%s\n' $zones | jq -R -s 'split("\n") | map(select(length > 0))')"

  local static_docs existing_outputs inventory_docs merged
  static_docs="$(step_context_docs "$step_id" | jq -R -s 'split("\n") | map(select(length > 0))')"

  existing_outputs="$(step_outputs "$step_id" | while read -r out; do
    [[ -z "$out" ]] && continue
    local abs
    abs="$(resolve_repo_path "$out")"
    if [[ -f "$abs" ]]; then
      echo "$out"
    fi
  done | jq -R -s 'split("\n") | map(select(length > 0))')"

  inventory_docs="$(jq -r --argjson zones "$zone_filter" '
    [.files[] | select(.zone as $z | $zones | index($z)) | .path] | unique | .[]
  ' "$DOCS_INVENTORY" | jq -R -s 'split("\n") | map(select(length > 0))')"

  merged="$(jq -n \
    --argjson static "$static_docs" \
    --argjson existing "$existing_outputs" \
    --argjson inventory "$inventory_docs" \
    --argjson max "$max_docs" '
    ($static + $existing + $inventory) | unique | .[0:$max]
  ')"

  echo "$merged" | jq -r '.[]?'
}

existing_outputs_for_step() {
  local step_id="$1"
  step_outputs "$step_id" | while read -r out; do
    [[ -z "$out" ]] && continue
    local abs
    abs="$(resolve_repo_path "$out")"
    if [[ -f "$abs" ]]; then
      echo "$out"
    fi
  done
}

step_can_auto_skip() {
  local step_id="$1"
  local kind phase
  kind="$(get_step_field "$step_id" kind)"
  phase="$(get_step_field "$step_id" phase)"

  if [[ "$kind" == "gate" ]]; then
    return 1
  fi

  if [[ "$phase" -ge 4 ]]; then
    if [[ "$step_id" == "harness-scaffold" ]]; then
      [[ -d "${REPO_ROOT}/ai-harness" ]] || return 1
    fi
    if [[ "$step_id" == "repo-bootstrap" ]]; then
      [[ -f "${REPO_ROOT}/package.json" ]] || return 1
    fi
  fi

  local out
  while IFS= read -r out; do
    [[ -z "$out" ]] && continue
    local abs
    abs="$(resolve_repo_path "$out")"
    if [[ "$out" == */ ]]; then
      [[ -d "$abs" ]] || return 1
    elif [[ ! -f "$abs" ]]; then
      return 1
    fi
  done < <(step_outputs "$step_id")

  return 0
}
