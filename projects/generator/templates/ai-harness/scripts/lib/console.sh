#!/usr/bin/env bash
# Terminal styling for harness scripts — dependency-free, TTY-aware ANSI helpers.

aih_color_enabled() {
  if [[ -n "${NO_COLOR:-}" || -n "${AIH_NO_COLOR:-}" ]]; then
    return 1
  fi
  if [[ -n "${FORCE_COLOR:-}" ]]; then
    return 0
  fi
  # npm run often leaves stdout non-TTY while stderr stays interactive
  [[ -t 1 || -t 2 ]]
}

aih_apply() {
  local code="$1"
  shift
  if aih_color_enabled; then
    printf '\033[%sm%s\033[0m' "$code" "$*"
  else
    printf '%s' "$*"
  fi
}

aih_bold() { aih_apply "1" "$@"; }
aih_dim() { aih_apply "2" "$@"; }
aih_red() { aih_apply "31" "$@"; }
aih_green() { aih_apply "32" "$@"; }
aih_yellow() { aih_apply "33" "$@"; }
aih_blue() { aih_apply "34" "$@"; }
aih_magenta() { aih_apply "35" "$@"; }
aih_cyan() { aih_apply "36" "$@"; }

aih_section_border() {
  aih_dim "════════════════════════════════════════"
}

aih_section_title() {
  local kind="$1"
  local title="$2"
  case "$kind" in
    loop)
      aih_apply "1;35" "$title"
      ;;
    iteration)
      aih_apply "1;36" "$title"
      ;;
    alert)
      aih_apply "1;33" "$title"
      ;;
    *)
      aih_apply "1;36" "$title"
      ;;
  esac
}

aih_blank() {
  echo ""
}

# Usage: aih_section "title" [kind]
# kind: loop (magenta) | iteration (cyan, default) | alert (yellow)
aih_section() {
  local title="$1"
  local kind="${2:-iteration}"
  local border
  border="$(aih_section_border)"
  printf '\n%s\n' "$border"
  aih_section_title "$kind" "$title"
  printf '\n%s\n' "$border"
}

aih_step() {
  aih_apply "1;34" "▸ $*"
  printf '\n'
}

aih_info() {
  aih_dim "$*"
  printf '\n'
}

aih_ok() {
  aih_apply "32" "✓ $*"
  printf '\n'
}

aih_warn() {
  aih_apply "33" "WARN: $*" >&2
  printf '\n' >&2
}

aih_err() {
  aih_apply "31" "ERROR: $*" >&2
  printf '\n' >&2
}

aih_kv() {
  local key="$1"
  local value="$2"
  printf '  %s  %s\n' "$(aih_dim "$key")" "$(aih_bold "$value")"
}

aih_agent_begin() {
  printf '%s%s%s\n' "$(aih_dim "─── ")" "$(aih_cyan "$*")" "$(aih_dim " ───")"
}

aih_agent_end() {
  local exit_status="$1"
  if [[ "$exit_status" -eq 0 ]]; then
    printf '%s%s%s\n' "$(aih_dim "─── ")" "$(aih_green "done")" "$(aih_dim " ───")"
  else
    printf '%s%s%s\n' "$(aih_dim "─── ")" "$(aih_red "failed (exit ${exit_status})")" "$(aih_dim " ───")"
  fi
}

# Computational check progress (run-checks.sh)
aih_check_begin() {
  printf '  %s %s\n' "$(aih_cyan "→")" "$(aih_bold "$*")"
}

aih_check_ok() {
  printf '  %s %s\n' "$(aih_green "✓")" "$*"
}

aih_check_fail() {
  printf '  %s %s\n' "$(aih_red "✗")" "$*" >&2
}

aih_check_skip() {
  printf '  %s %s\n' "$(aih_dim "⊘")" "$(aih_dim "$*")"
}
