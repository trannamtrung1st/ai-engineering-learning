#!/usr/bin/env bash
# Terminal styling for generator scripts — dependency-free, TTY-aware ANSI helpers.

gen_color_enabled() {
  if [[ -n "${NO_COLOR:-}" || -n "${GEN_NO_COLOR:-}" ]]; then
    return 1
  fi
  if [[ -n "${FORCE_COLOR:-}" ]]; then
    return 0
  fi
  [[ -t 1 || -t 2 ]]
}

gen_apply() {
  local code="$1"
  shift
  if gen_color_enabled; then
    printf '\033[%sm%s\033[0m' "$code" "$*"
  else
    printf '%s' "$*"
  fi
}

gen_bold() { gen_apply "1" "$@"; }
gen_dim() { gen_apply "2" "$@"; }
gen_red() { gen_apply "31" "$@"; }
gen_green() { gen_apply "32" "$@"; }
gen_yellow() { gen_apply "33" "$@"; }
gen_blue() { gen_apply "34" "$@"; }
gen_cyan() { gen_apply "36" "$@"; }

gen_section_border() {
  gen_dim "════════════════════════════════════════"
}

gen_blank() {
  echo ""
}

gen_section() {
  local title="$1"
  local kind="${2:-iteration}"
  printf '\n%s\n' "$(gen_section_border)"
  case "$kind" in
    loop) gen_apply "1;35" "$title" ;;
    alert) gen_apply "1;33" "$title" ;;
    *) gen_apply "1;36" "$title" ;;
  esac
  printf '\n%s\n' "$(gen_section_border)"
}

gen_step() {
  gen_apply "1;34" "▸ $*"
  printf '\n'
}

gen_info() {
  gen_dim "$*"
  printf '\n'
}

gen_ok() {
  gen_apply "32" "✓ $*"
  printf '\n'
}

gen_warn() {
  gen_apply "33" "WARN: $*" >&2
  printf '\n' >&2
}

gen_err() {
  gen_apply "31" "ERROR: $*" >&2
  printf '\n' >&2
}

gen_kv() {
  local key="$1"
  local value="$2"
  printf '  %s  %s\n' "$(gen_dim "$key")" "$(gen_bold "$value")"
}

gen_agent_begin() {
  printf '%s%s%s\n' "$(gen_dim "─── ")" "$(gen_cyan "$*")" "$(gen_dim " ───")"
}

gen_agent_end() {
  local exit_status="$1"
  if [[ "$exit_status" -eq 0 ]]; then
    printf '%s%s%s\n' "$(gen_dim "─── ")" "$(gen_green "done")" "$(gen_dim " ───")"
  else
    printf '%s%s%s\n' "$(gen_dim "─── ")" "$(gen_red "failed (exit ${exit_status})")" "$(gen_dim " ───")"
  fi
}
