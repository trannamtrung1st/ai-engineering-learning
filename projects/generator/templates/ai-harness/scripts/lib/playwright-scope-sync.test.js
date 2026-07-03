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
    ${body}
  `;
  return execFileSync("bash", ["-c", script], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function setupHarnessFixture() {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), "aih-playwright-scope-repo-"));
  const harnessRoot = path.join(repoRoot, "ai-harness");
  fs.mkdirSync(path.join(harnessRoot, "generated", "runs"), { recursive: true });
  fs.writeFileSync(
    path.join(harnessRoot, "whole-app-backlog.json"),
    JSON.stringify(
      {
        branchName: "aih/test",
        slices: [{ id: "slice-a", passes: false, testRequirements: {} }],
      },
      null,
      2,
    ) + "\n",
  );
  return { repoRoot, harnessRoot };
}

test("sync_playwright_spec_to_backlog appends spec path idempotently", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const spec = "tests/playwright-ui/scenarios/slice-a.spec.ts";

  try {
    bashHarness(
      repoRoot,
      harnessRoot,
      `
        sync_playwright_spec_to_backlog slice-a "${spec}"
        sync_playwright_spec_to_backlog slice-a "${spec}"
        jq -r '.slices[] | select(.id=="slice-a") | .testRequirements.playwright | join(",")' "$BACKLOG"
      `,
    );

    const backlog = JSON.parse(fs.readFileSync(path.join(harnessRoot, "whole-app-backlog.json"), "utf8"));
    const playwright = backlog.slices.find((s) => s.id === "slice-a").testRequirements.playwright;
    assert.deepEqual(playwright, [spec]);
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("browser_test_owned_paths includes support dir and custom spec path", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const customSpec = "tests/playwright-ui/scenarios/custom.spec.ts";

  try {
    const output = bashHarness(
      repoRoot,
      harnessRoot,
      `browser_test_owned_paths slice-a run-1 "${customSpec}" | sort`,
    );
    const lines = output.split("\n").filter(Boolean);
    assert.ok(lines.includes(customSpec));
    assert.ok(lines.includes("tests/playwright-ui/src/support"));
    assert.ok(lines.includes("ai-harness/playwright-regression-index.json"));
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("revert_browser_test_workspace_changes removes dirty owned files", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const specRel = "tests/playwright-ui/scenarios/slice-a.spec.ts";
  const supportRel = "tests/playwright-ui/src/support/helper.ts";
  const specAbs = path.join(repoRoot, specRel);
  const supportAbs = path.join(repoRoot, supportRel);

  try {
    fs.mkdirSync(path.dirname(specAbs), { recursive: true });
    fs.mkdirSync(path.dirname(supportAbs), { recursive: true });
    fs.writeFileSync(specAbs, "original\n");
    fs.writeFileSync(supportAbs, "helper\n");

    execFileSync("git", ["init"], { cwd: repoRoot, stdio: "ignore" });
    execFileSync("git", ["config", "user.email", "test@example.com"], { cwd: repoRoot, stdio: "ignore" });
    execFileSync("git", ["config", "user.name", "Test"], { cwd: repoRoot, stdio: "ignore" });
    execFileSync("git", ["add", specRel], { cwd: repoRoot, stdio: "ignore" });
    execFileSync("git", ["commit", "-m", "init"], { cwd: repoRoot, stdio: "ignore" });

    fs.writeFileSync(specAbs, "dirty\n");
    fs.writeFileSync(supportAbs, "new helper\n");

    bashHarness(
      repoRoot,
      harnessRoot,
      `
        cd "${repoRoot}"
        revert_browser_test_workspace_changes slice-a run-1 "${specRel}"
      `,
    );

    assert.equal(fs.readFileSync(specAbs, "utf8"), "original\n");
    assert.equal(fs.existsSync(supportAbs), false);
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});
