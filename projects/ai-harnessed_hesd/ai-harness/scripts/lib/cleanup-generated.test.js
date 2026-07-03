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

function runCleanup(harnessRoot, env = {}) {
  const script = `
    set -euo pipefail
    source "${COMMON_SH}"
    HARNESS_ROOT="${harnessRoot}"
    REPO_ROOT="$(cd "${harnessRoot}/.." && pwd)"
    RUNS_DIR="${harnessRoot}/generated/runs"
    SCREENSHOTS_ROOT="${harnessRoot}/generated/runs/screenshots"
    UX_BUGS_ROOT="${harnessRoot}/generated/runs/ux-bugs"
    PLAYWRIGHT_MCP_OUTPUT_DIR="${harnessRoot}/generated/runs/playwright-mcp"
    LOOP_CONFIG="${LOOP_CONFIG}"
    cleanup_generated_artifacts
  `;
  execFileSync("bash", ["-c", script], {
    env: { ...process.env, ...env },
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function touchOld(filePath) {
  const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000);
  fs.utimesSync(filePath, twoHoursAgo, twoHoursAgo);
}

test("cleanup_generated_artifacts removes old files and keeps recent and protected runtime files", () => {
  const harnessRoot = fs.mkdtempSync(path.join(os.tmpdir(), "aih-cleanup-"));
  const runsDir = path.join(harnessRoot, "generated", "runs");
  const screenshotDir = path.join(runsDir, "screenshots", "slice-a", "implementer");
  const uxBugDir = path.join(runsDir, "ux-bugs", "slice-a");

  try {
    fs.mkdirSync(screenshotDir, { recursive: true });
    fs.mkdirSync(uxBugDir, { recursive: true });

    const oldRun = path.join(runsDir, "20240101T000000Z-checks.json");
    const recentRun = path.join(runsDir, "20250702T120000Z-agent.txt");
    const protectedLog = path.join(runsDir, "loop.log");
    const oldScreenshot = path.join(screenshotDir, "20240101T000000Z-login.png");
    const recentScreenshot = path.join(screenshotDir, "20250702T120000Z-login.png");
    const oldUxBug = path.join(uxBugDir, "20240101T000000Z.json");
    const recentUxBug = path.join(uxBugDir, "20250702T120000Z.json");

    for (const file of [
      oldRun,
      recentRun,
      protectedLog,
      oldScreenshot,
      recentScreenshot,
      oldUxBug,
      recentUxBug,
    ]) {
      fs.writeFileSync(file, "fixture\n");
    }

    touchOld(oldRun);
    touchOld(oldScreenshot);
    touchOld(oldUxBug);
    touchOld(protectedLog);

    runCleanup(harnessRoot, { AIH_GENERATED_RETENTION_MINUTES: "60" });

    assert.equal(fs.existsSync(oldRun), false);
    assert.equal(fs.existsSync(oldScreenshot), false);
    assert.equal(fs.existsSync(oldUxBug), false);
    assert.equal(fs.existsSync(recentRun), true);
    assert.equal(fs.existsSync(recentScreenshot), true);
    assert.equal(fs.existsSync(recentUxBug), true);
    assert.equal(fs.existsSync(protectedLog), true);
  } finally {
    fs.rmSync(harnessRoot, { recursive: true, force: true });
  }
});

test("cleanup_generated_artifacts respects AIH_SKIP_GENERATED_CLEANUP", () => {
  const harnessRoot = fs.mkdtempSync(path.join(os.tmpdir(), "aih-cleanup-skip-"));
  const runsDir = path.join(harnessRoot, "generated", "runs");

  try {
    fs.mkdirSync(runsDir, { recursive: true });
    const oldRun = path.join(runsDir, "20240101T000000Z-checks.json");
    fs.writeFileSync(oldRun, "fixture\n");
    touchOld(oldRun);

    runCleanup(harnessRoot, {
      AIH_GENERATED_RETENTION_MINUTES: "60",
      AIH_SKIP_GENERATED_CLEANUP: "1",
    });

    assert.equal(fs.existsSync(oldRun), true);
  } finally {
    fs.rmSync(harnessRoot, { recursive: true, force: true });
  }
});
