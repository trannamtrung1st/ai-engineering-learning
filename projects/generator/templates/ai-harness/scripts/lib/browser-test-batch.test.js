#!/usr/bin/env node
"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const HARNESS_TEMPLATE = path.resolve(__dirname, "..", "..");
const COMMON_SH = path.join(HARNESS_TEMPLATE, "scripts", "lib", "common.sh");
const LOOP_CONFIG = path.join(HARNESS_TEMPLATE, "workflows", "ralph-loop.json");

function bashHarness(repoRoot, harnessRoot, body) {
  const script = `
    set -euo pipefail
    source "${COMMON_SH}"
    HARNESS_ROOT="${harnessRoot}"
    REPO_ROOT="${repoRoot}"
    BACKLOG="${harnessRoot}/whole-app-backlog.json"
    LOOP_CONFIG="${LOOP_CONFIG}"
    TEST_CASE_INDEX="${harnessRoot}/test-case-index.json"
    RUNS_DIR="${harnessRoot}/generated/runs"
    ${body}
  `;
  return execFileSync("bash", ["-c", script], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function setupHarnessFixture() {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), "aih-browser-batch-repo-"));
  const harnessRoot = path.join(repoRoot, "ai-harness");
  fs.mkdirSync(path.join(harnessRoot, "generated", "runs"), { recursive: true });
  fs.writeFileSync(
    path.join(harnessRoot, "whole-app-backlog.json"),
    JSON.stringify(
      {
        branchName: "aih/test",
        slices: [{ id: "slice-a", passes: false, acceptance: ["AC-01"], testRequirements: {} }],
      },
      null,
      2,
    ) + "\n",
  );
  fs.mkdirSync(path.join(repoRoot, "docs", "test-cases", "items"), { recursive: true });
  fs.writeFileSync(
    path.join(repoRoot, "docs", "test-cases", "items", "AC-01.json"),
    JSON.stringify(
      {
        productItemId: "AC-01",
        version: 1,
        docFingerprint: "fp",
        generatedAt: "2026-01-01T00:00:00Z",
        cases: [
          { id: "TC-A-P2", category: "functional", layer: "browser", technique: "browser-journey", priority: "P2", traceability: ["AC-01"], title: "P2 case", preconditions: [], steps: ["s"], expected: "e" },
          { id: "TC-A-P0", category: "functional", layer: "browser", technique: "browser-journey", priority: "P0", traceability: ["AC-01"], title: "P0 case", preconditions: [], steps: ["s"], expected: "e" },
          { id: "TC-A-P1", category: "functional", layer: "browser", technique: "browser-journey", priority: "P1", traceability: ["AC-01"], title: "P1 case", preconditions: [], steps: ["s"], expected: "e" },
          { id: "TC-A-SKIP", category: "functional", layer: "browser", technique: "browser-journey", priority: "P0", harnessSkip: "physical-device", traceability: ["AC-01"], title: "Skipped", preconditions: [], steps: ["s"], expected: "e" },
          { id: "TC-A-INT", category: "functional", layer: "integration", technique: "api", priority: "P0", traceability: ["AC-01"], title: "Not browser", preconditions: [], steps: ["s"], expected: "e" },
        ],
      },
      null,
      2,
    ) + "\n",
  );
  return { repoRoot, harnessRoot };
}

test("list_runnable_browser_case_ids_for_slice sorts P0 before P1 before P2 and excludes harnessSkip", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  try {
    const output = bashHarness(
      repoRoot,
      harnessRoot,
      `list_runnable_browser_case_ids_for_slice slice-a`,
    );
    assert.equal(output, "TC-A-P0\nTC-A-P1\nTC-A-P2");
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("split_case_ids_into_batches chunks 23 ids at max 10 into 10+10+3", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const ids = Array.from({ length: 23 }, (_, i) => `TC-${String(i + 1).padStart(2, "0")}`);
  try {
    const output = bashHarness(
      repoRoot,
      harnessRoot,
      `
        split_case_ids_into_batches 10 ${ids.join(" ")}
      `,
    );
    const batches = output.split("\n").filter(Boolean).map((line) => JSON.parse(line));
    assert.equal(batches.length, 3);
    assert.equal(batches[0].length, 10);
    assert.equal(batches[1].length, 10);
    assert.equal(batches[2].length, 3);
    assert.deepEqual(batches.flat(), ids);
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("browser_test_max_cases_per_batch defaults to 10 and respects env override", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  try {
    const defaultMax = bashHarness(repoRoot, harnessRoot, `browser_test_max_cases_per_batch`);
    assert.equal(defaultMax, "10");

    const overridden = bashHarness(
      repoRoot,
      harnessRoot,
      `AIH_BROWSER_TEST_MAX_CASES_PER_BATCH=7 browser_test_max_cases_per_batch`,
    );
    assert.equal(overridden, "7");
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("browser_test_batching_enabled is false when maxCasesPerBatch is 0", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const customLoop = path.join(harnessRoot, "ralph-loop-custom.json");
  fs.copyFileSync(LOOP_CONFIG, customLoop);
  const loop = JSON.parse(fs.readFileSync(customLoop, "utf8"));
  loop.browserTest.maxCasesPerBatch = 0;
  fs.writeFileSync(customLoop, JSON.stringify(loop, null, 2) + "\n");
  try {
    const enabled = bashHarness(
      repoRoot,
      harnessRoot,
      `
        LOOP_CONFIG="${customLoop}"
        if browser_test_batching_enabled; then echo yes; else echo no; fi
      `,
    );
    assert.equal(enabled, "no");
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("validate_batch_case_results rejects missing and FAIL case lines", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const outfile = path.join(harnessRoot, "generated", "runs", "batch-validate.txt");
  fs.writeFileSync(
    outfile,
    "TC-A-P0: PASS\nTC-A-P1: FAIL — broken\nBROWSER_TEST_BATCH_PASS\n",
  );
  try {
    const failResult = bashHarness(
      repoRoot,
      harnessRoot,
      `
        if validate_batch_case_results "${outfile}" TC-A-P0 TC-A-P1; then echo pass; else echo fail; fi
      `,
    );
    assert.equal(failResult, "fail");

    fs.writeFileSync(outfile, "TC-A-P0: PASS\nTC-A-P1: SKIP — not-applicable\nBROWSER_TEST_BATCH_PASS\n");
    const passResult = bashHarness(
      repoRoot,
      harnessRoot,
      `
        if validate_batch_case_results "${outfile}" TC-A-P0 TC-A-P1; then echo pass; else echo fail; fi
      `,
    );
    assert.equal(passResult, "pass");

    fs.writeFileSync(outfile, "TC-A-P0: PASS\nBROWSER_TEST_BATCH_PASS\n");
    const missingResult = bashHarness(
      repoRoot,
      harnessRoot,
      `
        if validate_batch_case_results "${outfile}" TC-A-P0 TC-A-P1; then echo pass; else echo fail; fi
      `,
    );
    assert.equal(missingResult, "fail");
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});
