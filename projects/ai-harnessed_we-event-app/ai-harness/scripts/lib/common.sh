#!/usr/bin/env bash
# Shared harness utilities
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$(cd "${HARNESS_ROOT}/.." && pwd)"

BACKLOG="${HARNESS_ROOT}/whole-app-backlog.json"
TEST_CASE_INDEX="${HARNESS_ROOT}/test-case-index.json"
TESTGEN_DOCS_MAP="${HARNESS_ROOT}/config/testgen-docs-map.json"
LOOP_CONFIG="${HARNESS_ROOT}/workflows/ralph-loop.json"
TESTGEN_CONFIG="${HARNESS_ROOT}/workflows/testgen-loop.json"
MODELS_CONFIG="${HARNESS_ROOT}/config/models.json"
CONTEXT_MAP="${HARNESS_ROOT}/config/context-map.json"
STATE_DIR="${HARNESS_ROOT}/state"
RUNS_DIR="${HARNESS_ROOT}/generated/runs"
TEST_CASES_DIR="${REPO_ROOT}/docs/test-cases"
PREVIEW_PID_FILE="${RUNS_DIR}/preview-stack.pids"
PREVIEW_AUX_PID_FILE="${RUNS_DIR}/preview-aux.pids"
PREVIEW_WEB_LOG="${RUNS_DIR}/preview-web.log"
PREVIEW_API_LOG="${RUNS_DIR}/preview-api.log"
PREVIEW_DB_LOG="${RUNS_DIR}/preview-db.log"
PREVIEW_STACK_LOG="${RUNS_DIR}/preview-stack.log"
PREVIEW_COMBINED_LOG="${RUNS_DIR}/preview-combined.log"
PREVIEW_SUPERVISOR_STOP_FILE="${RUNS_DIR}/preview-supervisor.stop"
PREVIEW_WEB_REFRESH_FILE="${RUNS_DIR}/preview-web.refresh"
PLAYWRIGHT_MCP_LEGACY_DIR="${REPO_ROOT}/.playwright-mcp"
PLAYWRIGHT_MCP_OUTPUT_DIR="${RUNS_DIR}/playwright-mcp"

export HARNESS_ROOT REPO_ROOT BACKLOG TEST_CASE_INDEX TESTGEN_DOCS_MAP LOOP_CONFIG TESTGEN_CONFIG MODELS_CONFIG CONTEXT_MAP STATE_DIR RUNS_DIR TEST_CASES_DIR
export PREVIEW_PID_FILE PREVIEW_AUX_PID_FILE
export PREVIEW_WEB_LOG PREVIEW_API_LOG PREVIEW_DB_LOG PREVIEW_STACK_LOG PREVIEW_COMBINED_LOG
export PREVIEW_SUPERVISOR_STOP_FILE PREVIEW_WEB_REFRESH_FILE
export PLAYWRIGHT_MCP_LEGACY_DIR PLAYWRIGHT_MCP_OUTPUT_DIR

preview_log_files() {
  printf '%s\n' \
    "$PREVIEW_COMBINED_LOG" \
    "$PREVIEW_STACK_LOG" \
    "$PREVIEW_API_LOG" \
    "$PREVIEW_WEB_LOG" \
    "$PREVIEW_DB_LOG"
}

preview_log_ts() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

preview_write_log() {
  local tag="$1"
  local primary_log="${2:-}"
  local content="$3"
  local ts line
  ts="$(preview_log_ts)"
  line="[${ts}][${tag}] ${content}"
  ensure_runs_dir
  echo "$line" >> "$PREVIEW_COMBINED_LOG"
  if [[ -n "$primary_log" ]]; then
    echo "$line" >> "$primary_log"
  fi
}

preview_log_session_start() {
  local mode="${1:-dev}"
  local banner
  banner="======== preview session start mode=${mode} $(preview_log_ts) pid=$$ ========"
  ensure_runs_dir
  local log_file
  while IFS= read -r log_file; do
    echo "$banner" >> "$log_file"
  done < <(preview_log_files)
}

preview_log_stack() {
  preview_write_log "stack" "$PREVIEW_STACK_LOG" "$*"
}

preview_tee_process_log() {
  local tag="$1"
  local primary_log="$2"
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    preview_write_log "$tag" "$primary_log" "$line"
  done
}

stop_preview_log_followers() {
  if [[ ! -f "$PREVIEW_AUX_PID_FILE" ]]; then
    return 0
  fi
  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    terminate_pid "$pid"
  done < "$PREVIEW_AUX_PID_FILE"
  rm -f "$PREVIEW_AUX_PID_FILE"
}

start_preview_db_log_follower() {
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  ensure_runs_dir
  stop_preview_log_followers
  : > "$PREVIEW_AUX_PID_FILE"
  (
    docker compose logs -f --tail=50 db 2>&1 | preview_tee_process_log "db" "$PREVIEW_DB_LOG"
  ) &
  echo $! >> "$PREVIEW_AUX_PID_FILE"
  preview_log_stack "db log follower started (pid=$!)"
}

start_preview_compose_log_follower() {
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  ensure_runs_dir
  stop_preview_log_followers
  : > "$PREVIEW_AUX_PID_FILE"
  (
    docker compose --profile full-preview logs -f --tail=100 2>&1 | preview_tee_process_log "compose" "$PREVIEW_STACK_LOG"
  ) &
  echo $! >> "$PREVIEW_AUX_PID_FILE"
  preview_log_stack "compose log follower started (pid=$!)"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_harness_deps() {
  require_cmd jq
}

# Search files for pattern. Uses rg when installed, otherwise grep -r.
search_files() {
  local pattern="$1"
  shift
  local paths=("$@")
  [[ ${#paths[@]} -eq 0 ]] && return 0
  if command -v rg >/dev/null 2>&1; then
    rg -i -l "$pattern" "${paths[@]}" 2>/dev/null || true
  else
    grep -Ri -l -E "$pattern" "${paths[@]}" 2>/dev/null || true
  fi
}

file_contains() {
  local pattern="$1"
  local file="$2"
  if command -v rg >/dev/null 2>&1; then
    rg -q "$pattern" "$file" 2>/dev/null
  else
    grep -qE "$pattern" "$file" 2>/dev/null
  fi
}

require_agent() {
  AGENT_BIN="$(resolve_agent_bin)"
  if [[ -z "$AGENT_BIN" ]]; then
    echo "ERROR: Cursor CLI not found. Install: curl https://cursor.com/install -fsS | bash" >&2
    echo "Then authenticate: agent login" >&2
    exit 1
  fi
  export AGENT_BIN
}

get_model() {
  local key="${1:-default}"
  if [[ "$key" == "default" && -n "${AIH_MODEL:-}" ]]; then
    echo "$AIH_MODEL"
    return
  fi
  if [[ "$key" == "reviewer" && -n "${AIH_REVIEWER_MODEL:-}" ]]; then
    echo "$AIH_REVIEWER_MODEL"
    return
  fi
  if [[ "$key" == "tester" && -n "${AIH_TESTER_MODEL:-}" ]]; then
    echo "$AIH_TESTER_MODEL"
    return
  fi
  if [[ "$key" == "testgen" && -n "${AIH_TESTGEN_MODEL:-}" ]]; then
    echo "$AIH_TESTGEN_MODEL"
    return
  fi
  jq -r --arg k "$key" '.[$k] // .default' "$MODELS_CONFIG"
}

resolve_agent_bin() {
  if command -v agent >/dev/null 2>&1; then
    echo "agent"
  elif command -v cursor-agent >/dev/null 2>&1; then
    echo "cursor-agent"
  else
    echo ""
  fi
}

print_harness_env() {
  local bin
  bin="$(resolve_agent_bin)"
  if [[ -n "$bin" ]]; then
    echo "Agent: ${bin} | Model: $(get_model default) | Reviewer: $(get_model reviewer) | Tester: $(get_model tester) | TestGen: $(get_model testgen)"
  else
    echo "Agent: not installed (curl https://cursor.com/install -fsS | bash)"
  fi
  echo "Auth: agent login (OAuth, one-time per machine)"
  echo "Overrides: AIH_MODEL=... AIH_SKIP_AGENT=1 AIH_SKIP_REVIEW=1"
}

run_id() {
  date -u +"%Y%m%dT%H%M%SZ"
}

ensure_runs_dir() {
  mkdir -p "$RUNS_DIR"
}

all_slices_pass() {
  local pending
  pending="$(jq '[.slices[] | select(.passes == false)] | length' "$BACKLOG")"
  [[ "$pending" -eq 0 ]]
}

pick_next_slice_id() {
  jq -r '
    [.slices[] | select(.passes == false)]
    | sort_by(.priority)
    | .[0].id // empty
  ' "$BACKLOG"
}

get_slice_field() {
  local slice_id="$1"
  local field="$2"
  jq -r --arg id "$slice_id" --arg f "$field" '
    .slices[] | select(.id == $id) | .[$f]
  ' "$BACKLOG"
}

get_slice_json() {
  local slice_id="$1"
  jq -c --arg id "$slice_id" '.slices[] | select(.id == $id)' "$BACKLOG"
}

test_case_gate_mode() {
  if [[ "${AIH_SKIP_TESTGEN_GATE:-}" == "1" ]]; then
    echo "optional"
    return
  fi
  jq -r '.testCaseGate.mode // "optional"' "$LOOP_CONFIG"
}

slice_missing_test_case_tags() {
  local slice_id="$1"
  local ref
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    if ! requirement_tag_test_cases_current "$ref"; then
      echo "$ref"
    fi
  done < <(slice_requirement_tag_refs "$slice_id")
}

mark_slice_passed() {
  local slice_id="$1"
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$slice_id" '
    .slices |= map(if .id == $id then .passes = true else . end)
  ' "$BACKLOG" > "$tmp" && mv "$tmp" "$BACKLOG"
}

test_case_artifact_path() {
  local requirement_tag="$1"
  printf 'docs/test-cases/items/%s.json' "$requirement_tag"
}

test_case_artifact_abs() {
  local requirement_tag="$1"
  echo "${REPO_ROOT}/$(test_case_artifact_path "$requirement_tag")"
}

test_case_stale_artifact_path() {
  local requirement_tag="$1"
  printf 'docs/test-cases/items/%s.stale.json' "$requirement_tag"
}

test_case_stale_artifact_abs() {
  local requirement_tag="$1"
  echo "${REPO_ROOT}/$(test_case_stale_artifact_path "$requirement_tag")"
}

# Legacy: drift used to mv artifacts to .stale.json — restore so the agent can review in place.
ensure_test_case_artifact_restored() {
  local requirement_tag="$1"
  local artifact_path stale_path
  artifact_path="$(test_case_artifact_abs "$requirement_tag")"
  stale_path="$(test_case_stale_artifact_abs "$requirement_tag")"
  if [[ ! -f "$artifact_path" && -f "$stale_path" ]]; then
    cp -f "$stale_path" "$artifact_path"
    echo "==> ${requirement_tag}: restored legacy .stale.json to $(test_case_artifact_path "$requirement_tag")"
  fi
}

testgen_regeneration_mode() {
  jq -r '.regeneration.mode // "incremental"' "$TESTGEN_CONFIG" 2>/dev/null || echo "incremental"
}

format_existing_artifact_review_block() {
  local requirement_tag="$1"
  local artifact_path artifact_abs mode case_count id_list stored_fp
  artifact_path="$(test_case_artifact_path "$requirement_tag")"
  artifact_abs="$(test_case_artifact_abs "$requirement_tag")"
  mode="$(testgen_regeneration_mode)"

  if [[ ! -f "$artifact_abs" ]]; then
    return 0
  fi

  if [[ "$mode" == "full" ]]; then
    cat <<EOF
## Existing artifact (reference)

An artifact already exists at \`${artifact_path}\`. Regeneration mode is **full** — rewrite from current docs. You may use the existing file as reference but replace content as needed.

EOF
    return 0
  fi

  case_count="$(jq '.cases | length' "$artifact_abs")"
  id_list="$(jq -r '.cases[].id' "$artifact_abs" | paste -sd ', ' -)"
  stored_fp="$(jq -r --arg id "$requirement_tag" '.tags[$id].docFingerprint // ""' "$TEST_CASE_INDEX")"

  cat <<EOF
## Review and update existing artifact

The test case artifact at \`${artifact_path}\` is **out of date** (\`test-case-index.json\` marks this tag \`current: false\` — docs changed since last generation).

**Read the existing file first.** Update only what current docs require — do not rewrite from scratch.

### Review rules

1. **Keep** cases that still match current docs; edit only affected fields (\`traceability\`, \`title\`, \`preconditions\`, \`steps\`, \`expected\`, \`edgeCase\`, \`priority\`).
2. **Add** cases for new doc requirements or coverage gaps (self-check below). Append new IDs; do not renumber existing ones.
3. **Remove** cases only when docs explicitly drop that scenario.
4. Set \`docFingerprint\` to the value in this prompt and refresh \`generatedAt\`.
$( [[ -n "$stored_fp" && "$stored_fp" != "null" ]] && printf '5. Index stored fingerprint: `%s` (artifact may still carry an older `docFingerprint`).\n' "$stored_fp" )

### Existing artifact summary

- **Path:** \`${artifact_path}\`
- **Case count:** ${case_count}
- **Case IDs:** ${id_list}

EOF
}

format_regeneration_finish_hint() {
  local requirement_tag="$1"
  local artifact_abs mode
  artifact_abs="$(test_case_artifact_abs "$requirement_tag")"
  mode="$(testgen_regeneration_mode)"

  if [[ -f "$artifact_abs" && "$mode" == "incremental" ]]; then
    echo "Finish in **one pass** — review the existing artifact against docs; update only what changed. Generate specs only — no implementation."
    return 0
  fi
  echo "Finish in **one pass**. Generate specs only — no implementation."
}

valid_requirement_tag() {
  local tag="$1"
  [[ "$tag" =~ ^(AC|FR|BR|NFR)-[0-9]+$ ]]
}

require_valid_requirement_tag() {
  local tag="$1"
  if ! valid_requirement_tag "$tag"; then
    echo "ERROR: invalid requirement tag: ${tag} (expected AC-*, FR-*, BR-*, or NFR-*)" >&2
    exit 1
  fi
}

slices_for_requirement_tag() {
  local requirement_tag="$1"
  jq -r --arg tag "$requirement_tag" '
    .slices[] | select(.acceptance[]? == $tag) |
    "- `\(.id)`: \(.description // "") (acceptance: \(.acceptance | join(", ")))"
  ' "$BACKLOG" 2>/dev/null || true
}

format_enhancement_artifact_block() {
  local requirement_tag="$1"
  local artifact_path artifact_abs case_count id_list
  artifact_path="$(test_case_artifact_path "$requirement_tag")"
  artifact_abs="$(test_case_artifact_abs "$requirement_tag")"

  if [[ ! -f "$artifact_abs" ]]; then
    cat <<EOF
## Artifact status

No test case artifact exists yet at \`${artifact_path}\`. Create one per docs, validation policy, and the enhancement instructions below.

EOF
    return 0
  fi

  case_count="$(jq '.cases | length' "$artifact_abs")"
  id_list="$(jq -r '.cases[].id' "$artifact_abs" | paste -sd ', ' -)"

  cat <<EOF
## Existing artifact (incremental update)

**Read the existing file first** at \`${artifact_path}\`. Apply the enhancement instructions below — do not rewrite from scratch.

### Update rules

1. **Keep** cases that remain valid; edit only affected fields.
2. **Add** cases per instructions; append new IDs; do not renumber existing ones.
3. **Remove** cases only when instructions or docs explicitly drop that scenario.
4. Set \`docFingerprint\` to the value in this prompt and refresh \`generatedAt\`.

### Existing artifact summary

- **Path:** \`${artifact_path}\`
- **Case count:** ${case_count}
- **Case IDs:** ${id_list}

EOF
}

format_testgen_enhancement_block() {
  local requirement_tag="$1"
  local instructions="$2"
  local extra_context="${3:-}"

  local slices_block
  slices_block="$(slices_for_requirement_tag "$requirement_tag")"
  if [[ -z "$slices_block" ]]; then
    slices_block="_(no backlog slices reference this tag)_"
  fi

  cat <<EOF
## Enhancement request (human-directed)

Apply these improvements to the test case artifact. This is **ad-hoc** — not doc-drift driven.
Keep valid cases; add, edit, or remove per instructions. Append new case IDs; do not renumber.

### Instructions

${instructions}

### Related implementation slices

${slices_block}

EOF

  format_enhancement_artifact_block "$requirement_tag"

  if [[ -n "$extra_context" ]]; then
    cat <<EOF
### Extra context paths (read as needed)

${extra_context}

EOF
  fi
}

requirement_tag_priority() {
  local tag="$1"
  local num
  if [[ "$tag" =~ ^AC-([0-9]+)$ ]]; then
    num="${BASH_REMATCH[1]}"
    echo $((10#$num))
  elif [[ "$tag" =~ ^FR-([0-9]+)$ ]]; then
    num="${BASH_REMATCH[1]}"
    echo $((100 + 10#$num))
  elif [[ "$tag" =~ ^BR-([0-9]+)$ ]]; then
    num="${BASH_REMATCH[1]}"
    echo $((200 + 10#$num))
  elif [[ "$tag" =~ ^NFR-([0-9]+)$ ]]; then
    num="${BASH_REMATCH[1]}"
    echo $((300 + 10#$num))
  else
    echo 999
  fi
}

all_requirement_tag_ids() {
  {
    jq -r '.slices[].acceptance[]?' "$BACKLOG" 2>/dev/null || true
    jq -r '
      [
        (.catalog.FR // []),
        (.catalog.BR // []),
        (.catalog.AC // []),
        (.catalog.NFR // [])
      ] | add | .[]
    ' "$TESTGEN_DOCS_MAP" 2>/dev/null || true
  } | sort -u
}

all_requirement_tags_sorted() {
  local tag prio
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    prio="$(requirement_tag_priority "$tag")"
    printf '%05d\t%s\n' "$prio" "$tag"
  done < <(all_requirement_tag_ids) | sort -n | cut -f2-
}

requirement_tag_test_cases_current() {
  local requirement_tag="$1"
  local current
  current="$(jq -r --arg id "$requirement_tag" '.tags[$id].current // false' "$TEST_CASE_INDEX")"
  [[ "$current" == "true" ]]
}

slice_test_cases_current() {
  local slice_id="$1"
  local ref
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    if ! requirement_tag_test_cases_current "$ref"; then
      return 1
    fi
  done < <(slice_requirement_tag_refs "$slice_id")
  return 0
}

all_test_cases_current() {
  local tag
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    if ! requirement_tag_test_cases_current "$tag"; then
      return 1
    fi
  done < <(all_requirement_tags_sorted)
  return 0
}

pick_next_testgen_requirement_tag() {
  local tag
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    if ! requirement_tag_test_cases_current "$tag"; then
      echo "$tag"
      return 0
    fi
  done < <(all_requirement_tags_sorted)
  echo ""
}

mark_test_cases_current() {
  local requirement_tag="$1"
  local fingerprint="$2"
  local generated_at="${3:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$requirement_tag" --arg fp "$fingerprint" --arg ts "$generated_at" '
    .tags[$id] = {
      current: true,
      docFingerprint: $fp,
      generatedAt: $ts
    }
  ' "$TEST_CASE_INDEX" > "$tmp" && mv "$tmp" "$TEST_CASE_INDEX"
}

reset_requirement_tag_on_doc_drift() {
  local requirement_tag="$1"
  local live_fp="$2"
  ensure_test_case_artifact_restored "$requirement_tag"
  local tmp pi_tmp
  tmp="$(mktemp)"
  jq --arg id "$requirement_tag" --arg fp "$live_fp" '
    .tags[$id] = {
      current: false,
      docFingerprint: $fp,
      generatedAt: null
    }
  ' "$TEST_CASE_INDEX" > "$tmp" && mv "$tmp" "$TEST_CASE_INDEX"

  pi_tmp="$(mktemp)"
  jq --arg ref "$requirement_tag" '
    .slices |= map(
      if (.acceptance // [] | index($ref)) then .passes = false else . end
    )
  ' "$BACKLOG" > "$pi_tmp" && mv "$pi_tmp" "$BACKLOG"
  append_guardrail "$requirement_tag" "Docs changed — test cases need review (index current=false; fingerprint=${live_fp})"
}

load_test_cases_json_for_slice() {
  local slice_id="$1"
  local refs merged="[]"
  refs="$(jq -r --arg id "$slice_id" '.slices[] | select(.id == $id) | .acceptance[]?' "$BACKLOG")"
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    local artifact cases
    artifact="$(test_case_artifact_abs "$ref")"
    [[ -f "$artifact" ]] || continue
    cases="$(jq -c '.cases // []' "$artifact")"
    merged="$(jq -c --argjson c "$cases" '. + $c' <<< "$merged")"
  done <<< "$refs"
  jq -n --arg slice "$slice_id" --argjson cases "$merged" \
    '{sliceId: $slice, requirementTags: [], cases: $cases}'
}

slice_requirement_tag_refs() {
  local slice_id="$1"
  jq -r --arg id "$slice_id" '.slices[] | select(.id == $id) | .acceptance[]?' "$BACKLOG"
}

# Back-compat aliases
slice_product_item_refs() { slice_requirement_tag_refs "$@"; }
product_item_test_cases_current() { requirement_tag_test_cases_current "$@"; }
pick_next_testgen_product_item_id() { pick_next_testgen_requirement_tag; }
reset_product_item_on_doc_drift() { reset_requirement_tag_on_doc_drift "$@"; }

# Testgen agent: writes test case artifacts only (no Playwright MCP).
agent_invoke_testgen() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args=(-p --force --trust --output-format text --model "$model")
  if [[ -n "$outfile" ]]; then
    "$AGENT_BIN" "${args[@]}" "$prompt" | tee "$outfile"
    return "${PIPESTATUS[0]}"
  fi
  "$AGENT_BIN" "${args[@]}" "$prompt"
}

append_guardrail() {
  local slice_id="$1"
  local message="$2"
  echo "- [${slice_id}] ${message}" >> "${STATE_DIR}/guardrails.md"
}

append_progress() {
  local slice_id="$1"
  local status="$2"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "- ${ts} | ${slice_id} | ${status}" >> "${STATE_DIR}/progress.md"
}

write_run_report() {
  local name="$1"
  local content="$2"
  ensure_runs_dir
  echo "$content" > "${RUNS_DIR}/${name}"
}

slice_uses_browser_mcp() {
  local slice_id="${1:-}"
  slice_requires_web_runtime "$slice_id" || [[ "${AIH_BROWSER_MCP:-}" == "1" ]]
}

slice_requires_browser_test() {
  local slice_id="${1:-}"
  [[ -n "$slice_id" ]] || return 1
  local agent
  agent="$(get_slice_field "$slice_id" agent)"
  jq -e --arg agent "$agent" '.browserTest.activeWhenAgent[]? | select(. == $agent)' "$LOOP_CONFIG" >/dev/null 2>&1
}

playwright_mcp_artifact_dirs() {
  printf '%s\n' "$PLAYWRIGHT_MCP_LEGACY_DIR" "$PLAYWRIGHT_MCP_OUTPUT_DIR"
}

cleanup_playwright_mcp_dir() {
  local dir="$1"
  local keep="${2:-0}"
  [[ -d "$dir" ]] || return 0

  if [[ "$keep" -le 0 ]]; then
    find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
    return 0
  fi

  local f
  for f in $(ls -t "$dir" 2>/dev/null | tail -n +$((keep + 1))); do
    rm -f "${dir}/${f}"
  done
}

cleanup_playwright_mcp_artifacts() {
  if [[ "${AIH_SKIP_PLAYWRIGHT_MCP_CLEANUP:-}" == "1" ]]; then
    return 0
  fi

  local keep="${AIH_PLAYWRIGHT_MCP_KEEP:-0}"
  local dir removed=0
  ensure_runs_dir
  while IFS= read -r dir; do
    if [[ -d "$dir" ]] && [[ -n "$(ls -A "$dir" 2>/dev/null || true)" ]]; then
      cleanup_playwright_mcp_dir "$dir" "$keep"
      removed=1
    fi
  done < <(playwright_mcp_artifact_dirs)

  if [[ "$removed" -eq 1 ]]; then
    echo "==> Playwright MCP artifacts cleaned (keep=${keep})"
  fi
}

agent_invoke() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  local slice_id="${4:-${AIH_CHECK_SLICE:-}}"
  require_agent
  local -a args=(-p --force --output-format text --model "$model")
  if slice_uses_browser_mcp "$slice_id"; then
    args+=(--approve-mcps)
  fi
  if [[ -n "$outfile" ]]; then
    "$AGENT_BIN" "${args[@]}" "$prompt" | tee "$outfile"
    return "${PIPESTATUS[0]}"
  fi
  "$AGENT_BIN" "${args[@]}" "$prompt"
}

# Read-only reviewer: plan mode blocks edits; prompt forbids shell/tests.
agent_invoke_review() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args=(-p --force --trust --output-format text --model "$model" --mode plan)
  if [[ -n "$outfile" ]]; then
    "$AGENT_BIN" "${args[@]}" "$prompt" | tee "$outfile"
    return "${PIPESTATUS[0]}"
  fi
  "$AGENT_BIN" "${args[@]}" "$prompt"
}

# Browser tester: Playwright MCP enabled; prompt forbids file edits.
agent_invoke_browser_test() {
  local model="$1"
  local prompt="$2"
  local outfile="${3:-}"
  require_agent
  local -a args=(-p --force --trust --approve-mcps --output-format text --model "$model")
  if [[ -n "$outfile" ]]; then
    "$AGENT_BIN" "${args[@]}" "$prompt" | tee "$outfile"
    return "${PIPESTATUS[0]}"
  fi
  "$AGENT_BIN" "${args[@]}" "$prompt"
}

git_changed_files() {
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    return 0
  fi
  {
    git diff --name-only HEAD 2>/dev/null || true
    git diff --cached --name-only 2>/dev/null || true
    git ls-files --others --exclude-standard 2>/dev/null || true
  } | sed '/^$/d' | sort -u
}

git_path_has_changes() {
  local rel="$1"
  [[ -n "$rel" ]] || return 1
  if [[ -e "$REPO_ROOT/$rel" ]] && ! git ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
    return 0
  fi
  ! git diff --quiet -- "$rel" 2>/dev/null && return 0
  ! git diff --cached --quiet -- "$rel" 2>/dev/null && return 0
  return 1
}

git_commit_allowlisted_paths() {
  local message="$1"
  shift
  local paths=("$@")
  [[ ${#paths[@]} -gt 0 ]] || return 0
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    return 0
  fi

  local to_add=()
  local rel
  for rel in "${paths[@]}"; do
    [[ -n "$rel" ]] || continue
    [[ -e "$REPO_ROOT/$rel" ]] || continue
    if git_path_has_changes "$rel"; then
      to_add+=("$rel")
    fi
  done

  [[ ${#to_add[@]} -gt 0 ]] || return 0
  git add -- "${to_add[@]}"
  git commit -m "$message" --no-verify 2>/dev/null || true
}

testgen_owned_paths() {
  local requirement_tag="$1"
  printf '%s\n' \
    "$(test_case_artifact_path "$requirement_tag")" \
    "ai-harness/test-case-index.json" \
    "ai-harness/whole-app-backlog.json" \
    "ai-harness/state/progress.md"
}

git_commit_testgen_pass() {
  local requirement_tag="$1"
  local -a paths=()
  local path
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    paths+=("$path")
  done < <(testgen_owned_paths "$requirement_tag")
  git_commit_allowlisted_paths "aih: generate test cases for ${requirement_tag}" "${paths[@]}"
}

find_checks_report_for_slice() {
  local slice_id="$1"
  local run_id="${2:-}"
  if [[ -n "$run_id" && -f "${RUNS_DIR}/${run_id}-checks.json" ]]; then
    cat "${RUNS_DIR}/${run_id}-checks.json"
    return 0
  fi
  local f
  for f in $(ls -t "${RUNS_DIR}"/*-checks.json 2>/dev/null || true); do
    if jq -e --arg s "$slice_id" '.slice == $s and .pass == true' "$f" >/dev/null 2>&1; then
      cat "$f"
      return 0
    fi
  done
  echo '{"pass":false,"note":"no checks report found for slice"}'
}

find_browser_test_report_for_slice() {
  local slice_id="$1"
  local run_id="${2:-}"
  if [[ -n "$run_id" && -f "${RUNS_DIR}/${run_id}-browser-test.json" ]]; then
    cat "${RUNS_DIR}/${run_id}-browser-test.json"
    return 0
  fi
  local f
  for f in $(ls -t "${RUNS_DIR}"/*-browser-test.json 2>/dev/null || true); do
    if jq -e --arg s "$slice_id" '.slice == $s and (.pass == true or .skipped == true)' "$f" >/dev/null 2>&1; then
      cat "$f"
      return 0
    fi
  done
  echo '{"pass":false,"skipped":false,"note":"no browser test report found for slice"}'
}

find_latest_failed_run_id_for_slice() {
  local slice_id="$1"
  local artifact_kind="$2"
  local f
  for f in $(ls -t "${RUNS_DIR}"/*-"${artifact_kind}".json 2>/dev/null || true); do
    if jq -e --arg s "$slice_id" '.slice == $s and .pass == false' "$f" >/dev/null 2>&1; then
      if [[ "$artifact_kind" == "browser-test" ]]; then
        jq -e --arg s "$slice_id" '.slice == $s and .pass == false and (.skipped // false) == false' "$f" >/dev/null 2>&1 || continue
      fi
      basename "$f" "-${artifact_kind}.json"
      return 0
    fi
  done
  return 1
}

summarize_checks_failures() {
  local run_id="$1"
  local max_chars="${2:-32000}"
  local json_file="${RUNS_DIR}/${run_id}-checks.json"
  [[ -f "$json_file" ]] || return 1
  jq -e '.pass == false and ((.failures // []) | length) > 0' "$json_file" >/dev/null 2>&1 || return 1
  jq '{slice, timestamp, failureCount: (.failures | length), failures}' "$json_file" 2>/dev/null | head -c "$max_chars"
}

summarize_browser_test_failures() {
  local run_id="$1"
  local max_chars="${2:-12000}"
  local text_file="${RUNS_DIR}/${run_id}-browser-test.txt"
  local line block=""
  [[ -f "$text_file" ]] || return 1
  while IFS= read -r line; do
    if echo "$line" | grep -qE ': FAIL|BROWSER_TEST_FAIL|^\*\*cases:'; then
      block+="${line}"$'\n'
    fi
  done < "$text_file"
  [[ -n "$block" ]] || return 1
  printf '%s' "$block" | head -c "$max_chars"
}

summarize_review_failures() {
  local run_id="$1"
  local max_chars="${2:-12000}"
  local text_file="${RUNS_DIR}/${run_id}-review.txt"
  local block=""
  [[ -f "$text_file" ]] || return 1
  block="$(awk '
    /\*\*Blocker|### Blocker|## Blocker/ { capture=1 }
    capture { print }
  ' "$text_file")"
  if [[ -z "$block" ]]; then
    block="$(grep -E 'REVIEW_FAIL|Blocker|blocker|\bgap\b|missing|out of scope|not met|violat' -i "$text_file" 2>/dev/null || true)"
  fi
  [[ -n "$block" ]] || return 1
  printf '%s' "$block" | head -c "$max_chars"
}

build_implementer_prior_gate_feedback() {
  local slice_id="$1"
  local block sections=""
  local checks_run="" browser_run="" review_run=""

  if checks_run="$(find_latest_failed_run_id_for_slice "$slice_id" checks)"; then
    block="$(summarize_checks_failures "$checks_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      sections="${sections}### Computational checks failures (\`${checks_run}\`)

Fix every item in \`failures\` below before signaling \`SLICE_DONE\`.

\`\`\`json
${block}
\`\`\`

"
    fi
  fi

  if browser_run="$(find_latest_failed_run_id_for_slice "$slice_id" browser-test)"; then
    block="$(summarize_browser_test_failures "$browser_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      sections="${sections}### Browser test failures (\`${browser_run}\`)

Fix only the failed cases below before signaling \`SLICE_DONE\`.

\`\`\`
${block}
\`\`\`

"
    fi
  fi

  if review_run="$(find_latest_failed_run_id_for_slice "$slice_id" review)"; then
    block="$(summarize_review_failures "$review_run" 2>/dev/null || true)"
    if [[ -n "$block" ]]; then
      sections="${sections}### AI code review blockers (\`${review_run}\`)

Resolve the blockers below before signaling \`SLICE_DONE\`.

\`\`\`
${block}
\`\`\`

"
    fi
  fi

  [[ -n "$sections" ]] || return 0

  cat <<EOF
## Prior gate failures — address these first

This slice failed harness gates on a previous iteration. Only failure summaries are included below — fix them before signaling \`SLICE_DONE\`.

${sections}
EOF
}

# Backend/infra slices only require API runtime probes; frontend/test need web too.
slice_requires_web_runtime() {
  local slice_id="${1:-}"
  if [[ -z "$slice_id" ]]; then
    return 0
  fi
  local agent
  agent="$(get_slice_field "$slice_id" agent)"
  [[ "$agent" == "frontend" || "$agent" == "test" ]]
}

terminate_pid() {
  local pid="$1"
  [[ -z "$pid" ]] && return 0
  kill "$pid" 2>/dev/null || true
  pkill -P "$pid" 2>/dev/null || true
  local _
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.3
  done
  kill -9 "$pid" 2>/dev/null || true
  pkill -9 -P "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

preview_supervisor_script() {
  echo "${HARNESS_ROOT}/scripts/preview-supervisor.sh"
}

preview_stack_is_running() {
  [[ -f "$PREVIEW_PID_FILE" ]] || return 1
  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    kill -0 "$pid" 2>/dev/null && return 0
  done < "$PREVIEW_PID_FILE"
  return 1
}

read_preview_supervisor_pids() {
  PREVIEW_API_SUPERVISOR_PID=""
  PREVIEW_WEB_SUPERVISOR_PID=""
  [[ -f "$PREVIEW_PID_FILE" ]] || return 1
  local -a pids=()
  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    pids+=("$pid")
  done < "$PREVIEW_PID_FILE"
  [[ ${#pids[@]} -ge 1 ]] && PREVIEW_API_SUPERVISOR_PID="${pids[0]}"
  [[ ${#pids[@]} -ge 2 ]] && PREVIEW_WEB_SUPERVISOR_PID="${pids[1]}"
  export PREVIEW_API_SUPERVISOR_PID PREVIEW_WEB_SUPERVISOR_PID
}

stop_preview_supervisors() {
  ensure_runs_dir
  preview_log_stack "stopping preview supervisors"
  touch "$PREVIEW_SUPERVISOR_STOP_FILE"
  rm -f "$PREVIEW_WEB_REFRESH_FILE"

  if [[ -f "$PREVIEW_PID_FILE" ]]; then
    local pid
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      terminate_pid "$pid"
    done < "$PREVIEW_PID_FILE"
    rm -f "$PREVIEW_PID_FILE"
  fi

  stop_preview_log_followers
  sleep 0.5
  rm -f "$PREVIEW_SUPERVISOR_STOP_FILE"
  preview_log_stack "preview supervisors stopped"
}

# Kill preview-supervisor.sh processes left behind by interrupted preview-stack (^C).
stop_stray_preview_supervisors() {
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi

  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    [[ "$pid" == "$$" ]] && continue
    preview_log_stack "stopping stray preview supervisor (pid=${pid})"
    terminate_pid "$pid"
  done < <(pgrep -f 'preview-supervisor\.sh (api|web)' 2>/dev/null || true)
}

# Kill any process listening on preview API/web ports (orphan next dev after ^C).
stop_preview_port_listeners() {
  local api_port="${AIH_PREVIEW_API_PORT:-3001}"
  local web_port="${AIH_PREVIEW_WEB_PORT:-3000}"

  if ! command -v lsof >/dev/null 2>&1; then
    preview_log_stack "WARN: lsof unavailable — cannot verify preview ports are free"
    return 0
  fi

  local port port_pid
  for port in "$api_port" "$web_port"; do
    while IFS= read -r port_pid; do
      [[ -z "$port_pid" ]] && continue
      preview_log_stack "stopping listener on port ${port} (pid=${port_pid})"
      terminate_pid "$port_pid"
    done < <(lsof -ti ":${port}" 2>/dev/null || true)
  done
}

wait_for_preview_ports_free() {
  local api_port="${AIH_PREVIEW_API_PORT:-3001}"
  local web_port="${AIH_PREVIEW_WEB_PORT:-3000}"

  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi

  local port
  for port in "$api_port" "$web_port"; do
    local _
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      lsof -ti ":${port}" >/dev/null 2>&1 || break
      sleep 0.3
    done
  done
}

# Full dev-preview reset before start: supervisors, orphans, ports, then .next cache.
reset_dev_preview_stack() {
  preview_log_stack "resetting dev preview stack (supervisors, ports, .next)"
  stop_preview_supervisors
  stop_stray_preview_supervisors
  stop_preview_port_listeners
  wait_for_preview_ports_free
  remove_path_safely "$REPO_ROOT/apps/web/.next"
  preview_log_stack "dev preview stack reset complete"
}

# Tear down dev preview processes without clearing .next (used by preview:down).
stop_dev_preview_processes() {
  stop_preview_supervisors
  stop_stray_preview_supervisors
  stop_preview_port_listeners
  wait_for_preview_ports_free
}

start_preview_supervisors() {
  local supervisor_script
  supervisor_script="$(preview_supervisor_script)"
  ensure_runs_dir
  rm -f "$PREVIEW_SUPERVISOR_STOP_FILE" "$PREVIEW_WEB_REFRESH_FILE"
  : > "$PREVIEW_PID_FILE"

  "$supervisor_script" api &
  echo $! >> "$PREVIEW_PID_FILE"
  local api_sup=$!
  "$supervisor_script" web &
  echo $! >> "$PREVIEW_PID_FILE"
  local web_sup=$!
  preview_log_stack "supervisors started (api=${api_sup}, web=${web_sup})"
}

# Kill the dev child on a port so its supervisor restarts it.
nudge_preview_service_restart() {
  local port="$1"
  local self_pid="${2:-}"

  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi

  local port_pid
  while IFS= read -r port_pid; do
    [[ -z "$port_pid" ]] && continue
    [[ -n "$self_pid" && "$port_pid" == "$self_pid" ]] && continue
    [[ -n "${PREVIEW_WEB_SUPERVISOR_PID:-}" && "$port_pid" == "$PREVIEW_WEB_SUPERVISOR_PID" ]] && continue
    [[ -n "${PREVIEW_API_SUPERVISOR_PID:-}" && "$port_pid" == "$PREVIEW_API_SUPERVISOR_PID" ]] && continue
    terminate_pid "$port_pid"
  done < <(lsof -ti ":${port}" 2>/dev/null || true)
}

nudge_preview_api_restart() {
  read_preview_supervisor_pids || return 0
  nudge_preview_service_restart "${AIH_PREVIEW_API_PORT:-3001}"
}

nudge_preview_web_restart() {
  read_preview_supervisor_pids || return 0
  touch "$PREVIEW_WEB_REFRESH_FILE"
  nudge_preview_service_restart "${AIH_PREVIEW_WEB_PORT:-3000}"
}

remove_path_safely() {
  local target="$1"
  [[ -e "$target" ]] || return 0
  chmod -R u+w "$target" 2>/dev/null || true
  if rm -rf "$target" 2>/dev/null; then
    return 0
  fi
  local _
  for _ in 1 2 3 4 5; do
    sleep 0.5
    chmod -R u+w "$target" 2>/dev/null || true
    rm -rf "$target" 2>/dev/null && return 0
  done
  echo "WARN: could not remove ${target} (locked or permission denied); continuing" >&2
  return 0
}

stop_preview_web_process() {
  nudge_preview_web_restart
  sleep 0.5
}

clean_web_next_cache() {
  [[ -d "$REPO_ROOT/apps/web" ]] || return 0
  if preview_stack_is_running; then
    nudge_preview_web_restart
    stop_preview_port_listeners
    wait_for_preview_ports_free
  fi
  remove_path_safely "$REPO_ROOT/apps/web/.next"
}

print_preview_web_hint() {
  echo "  Hint: next build + next dev can corrupt apps/web/.next. Recovery:" >&2
  echo "    npm run aih:preview:down && rm -rf apps/web/.next && npm run aih:preview" >&2
  echo "  Logs: npm run aih:preview:logs -- web" >&2
  if [[ -f "$PREVIEW_WEB_LOG" ]]; then
    echo "  Last lines of ${PREVIEW_WEB_LOG}:" >&2
    tail -n 8 "$PREVIEW_WEB_LOG" >&2 || true
  fi
}

# After a full workspace build (production .next), stop stray dev servers and clear cache.
refresh_preview_web_after_build() {
  [[ -d "$REPO_ROOT/apps/web" ]] || return 0
  if preview_stack_is_running; then
    return 0
  fi
  stop_preview_web_process
  clean_web_next_cache
}

# Build all workspaces except web while preview dev is serving (avoids .next corruption).
run_build_for_checks() {
  local ws
  local pkg
  local -a workspaces=(
    "@we-event/api:apps/api"
    "@we-event/domain:packages/domain"
    "@we-event/config:packages/config"
    "@we-event/web:apps/web"
  )

  if preview_stack_is_running; then
    echo "Preview stack running — skipping @we-event/web build to preserve dev .next cache"
    for ws in "${workspaces[@]}"; do
      [[ "${ws##*:}" == "apps/web" ]] && continue
      pkg="${ws%%:*}"
      if [[ -f "$REPO_ROOT/${ws##*:}/package.json" ]] && jq -e --arg s "build" '.scripts[$s] // empty' "$REPO_ROOT/${ws##*:}/package.json" >/dev/null 2>&1; then
        npm run build --workspace "$pkg" || return 1
        if [[ "$pkg" == "@we-event/api" ]]; then
          nudge_preview_api_restart
        fi
      fi
    done
    return 0
  fi

  npm run build || return 1
}
