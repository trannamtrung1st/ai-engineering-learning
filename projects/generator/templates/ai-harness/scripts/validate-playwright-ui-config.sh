#!/usr/bin/env bash
# Validate Playwright UI workspace layout and config for browser-test close.
# Usage: validate-playwright-ui-config.sh <sliceId> [specRelPath]
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

SLICE_ID="${1:?slice id required}"
SPEC_REL="${2:-}"

PW_DIR="${REPO_ROOT}/tests/playwright-ui"
FAILURES=()
PASS=true

fail() {
  FAILURES+=("$1")
  PASS=false
}

if [[ ! -d "$PW_DIR" ]]; then
  fail "tests/playwright-ui workspace missing"
  printf 'ERROR: Playwright UI config validation failed for %s:\n' "$SLICE_ID" >&2
  printf '  - %s\n' "${FAILURES[@]}" >&2
  exit 1
fi

for req in package.json playwright.config.ts tsconfig.json; do
  if [[ ! -f "${PW_DIR}/${req}" ]]; then
    fail "missing ${req} under tests/playwright-ui"
  fi
done

if [[ -f "${PW_DIR}/package.json" ]] && ! jq -e '.scripts["test:playwright-ui"] // .scripts.test' "${PW_DIR}/package.json" >/dev/null 2>&1; then
  fail "package.json missing test:playwright-ui (or test) script"
fi

if [[ -f "${PW_DIR}/package.json" ]] && ! jq -e '.devDependencies["@playwright/test"] // .dependencies["@playwright/test"]' "${PW_DIR}/package.json" >/dev/null 2>&1; then
  fail "package.json missing @playwright/test dependency"
fi

expected_web_port="$(aih_web_port)"
if [[ -f "${PW_DIR}/playwright.config.ts" ]]; then
  if ! grep -qE 'testDir:[[:space:]]*["'\''][.]?/?scenarios["'\'']' "${PW_DIR}/playwright.config.ts"; then
    fail "playwright.config.ts testDir should point at ./scenarios"
  fi
  if ! grep -q 'PLAYWRIGHT_BASE_URL' "${PW_DIR}/playwright.config.ts" \
    && ! grep -q "localhost:${expected_web_port}" "${PW_DIR}/playwright.config.ts"; then
    fail "playwright.config.ts baseURL must use PLAYWRIGHT_BASE_URL or localhost:${expected_web_port} (preview web port)"
  fi
fi

constants_file="${PW_DIR}/src/support/constants.ts"
if [[ -f "$constants_file" ]]; then
  if ! grep -q 'PLAYWRIGHT_BASE_URL' "$constants_file" \
    && ! grep -q "localhost:${expected_web_port}" "$constants_file"; then
    fail "src/support/constants.ts WEB_BASE_URL must use PLAYWRIGHT_BASE_URL or localhost:${expected_web_port}"
  fi
else
  fail "missing tests/playwright-ui/src/support/constants.ts"
fi

if [[ -z "$SPEC_REL" ]]; then
  SPEC_REL="$(resolve_playwright_spec_for_slice "$SLICE_ID" 2>/dev/null || true)"
fi
SPEC_REL="$(normalize_repo_rel_path "$SPEC_REL")"

if [[ -n "$SPEC_REL" ]]; then
  if [[ ! -f "${REPO_ROOT}/${SPEC_REL}" ]]; then
    fail "Playwright spec not found: ${SPEC_REL}"
  elif ! grep -qE 'test(\.describe)?\s*\(' "${REPO_ROOT}/${SPEC_REL}" 2>/dev/null; then
    fail "Playwright spec has no test() blocks: ${SPEC_REL}"
  fi
elif slice_requires_playwright_regression_gate "$SLICE_ID"; then
  fail "no Playwright spec path for slice ${SLICE_ID} (emit playwright-regression: line in browser test output)"
fi

if [[ "$PASS" == true ]]; then
  spec_files="$(find "${PW_DIR}/scenarios" -maxdepth 1 -name '*.spec.ts' 2>/dev/null | wc -l | tr -d ' ')"
  if [[ -n "$SPEC_REL" || "$spec_files" -gt 0 ]]; then
    set +e
    list_out="$(cd "$PW_DIR" && npx playwright test --list 2>&1)"
    list_status=$?
    set -e
    if [[ "$list_status" -ne 0 ]]; then
      fail "npx playwright test --list failed (config or spec parse error)"
      while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        fail "  ${line}"
      done <<< "$list_out"
    fi
  fi
fi

if [[ "$PASS" == true ]]; then
  echo "OK: Playwright UI config valid for ${SLICE_ID}${SPEC_REL:+ (spec: ${SPEC_REL})}"
  exit 0
fi

echo "ERROR: Playwright UI config validation failed for ${SLICE_ID}:" >&2
printf '  - %s\n' "${FAILURES[@]}" >&2
exit 1
