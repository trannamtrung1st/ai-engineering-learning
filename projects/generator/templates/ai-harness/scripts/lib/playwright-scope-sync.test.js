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
        slices: [{ id: "slice-a", passes: false, acceptance: ["AC-01"], testRequirements: {} }],
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
    assert.ok(lines.includes("docs/test-cases/items/AC-01.json"));
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("slice_requires_playwright_regression_gate is true for frontend agent slices", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const backlogPath = path.join(harnessRoot, "whole-app-backlog.json");
  fs.writeFileSync(
    backlogPath,
    JSON.stringify(
      {
        branchName: "aih/test",
        slices: [{ id: "slice-ui", passes: false, agent: "frontend", acceptance: ["AC-01"] }],
      },
      null,
      2,
    ) + "\n",
  );

  try {
    const output = bashHarness(
      repoRoot,
      harnessRoot,
      `slice_requires_playwright_regression_gate slice-ui && echo yes || echo no`,
    );
    assert.equal(output.trim(), "yes");
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("ralph-loop profiles exclude test:playwright-ui from pre-browser checks", () => {
  const config = JSON.parse(fs.readFileSync(LOOP_CONFIG, "utf8"));
  assert.ok(!config.computationalChecks.profiles.full.includes("test:playwright-ui"));
  assert.ok(!config.computationalChecks.profiles.fast.includes("test:playwright-ui"));
  assert.equal(config.playwrightRegressionGate.enabled, true);
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

test("resolve_playwright_spec_for_slice skips playwright.config.ts and picks scenarios spec", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const specRel = "tests/playwright-ui/scenarios/slice-a.spec.ts";
  const specAbs = path.join(repoRoot, specRel);
  const backlogPath = path.join(harnessRoot, "whole-app-backlog.json");

  fs.mkdirSync(path.dirname(specAbs), { recursive: true });
  fs.writeFileSync(specAbs, "import { test } from '@playwright/test';\n");
  fs.writeFileSync(
    backlogPath,
    JSON.stringify(
      {
        branchName: "aih/test",
        slices: [
          {
            id: "slice-a",
            passes: false,
            acceptance: ["AC-01"],
            testRequirements: {
              playwright: [
                "tests/playwright-ui/playwright.config.ts",
                specRel,
                "tests/playwright-ui/src/support/auth.ts",
              ],
            },
          },
        ],
      },
      null,
      2,
    ) + "\n",
  );

  try {
    const resolved = bashHarness(
      repoRoot,
      harnessRoot,
      `resolve_playwright_spec_for_slice slice-a`,
    );
    assert.equal(resolved.trim(), specRel);
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("resolve_playwright_spec_for_slice returns repo-relative path for absolute backlog entry", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const specRel = "tests/playwright-ui/scenarios/slice-a.spec.ts";
  const specAbs = path.join(repoRoot, specRel);
  const backlogPath = path.join(harnessRoot, "whole-app-backlog.json");

  fs.mkdirSync(path.dirname(specAbs), { recursive: true });
  fs.writeFileSync(specAbs, "import { test } from '@playwright/test';\n");
  fs.writeFileSync(
    backlogPath,
    JSON.stringify(
      {
        branchName: "aih/test",
        slices: [
          {
            id: "slice-a",
            passes: false,
            acceptance: ["AC-01"],
            testRequirements: {
              playwright: [specAbs],
            },
          },
        ],
      },
      null,
      2,
    ) + "\n",
  );

  try {
    const resolved = bashHarness(
      repoRoot,
      harnessRoot,
      `resolve_playwright_spec_for_slice slice-a`,
    );
    assert.equal(resolved.trim(), specRel);
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("sync_playwright_spec_to_backlog keeps spec at playwright[0] when other entries exist", () => {
  const { repoRoot, harnessRoot } = setupHarnessFixture();
  const spec = "tests/playwright-ui/scenarios/slice-a.spec.ts";
  const backlogPath = path.join(harnessRoot, "whole-app-backlog.json");

  fs.writeFileSync(
    backlogPath,
    JSON.stringify(
      {
        branchName: "aih/test",
        slices: [
          {
            id: "slice-a",
            passes: false,
            acceptance: ["AC-01"],
            testRequirements: {
              playwright: [
                "tests/playwright-ui/playwright.config.ts",
                "tests/playwright-ui/src/support/auth.ts",
              ],
            },
          },
        ],
      },
      null,
      2,
    ) + "\n",
  );

  try {
    bashHarness(
      repoRoot,
      harnessRoot,
      `sync_playwright_spec_to_backlog slice-a "${spec}"`,
    );

    const backlog = JSON.parse(fs.readFileSync(backlogPath, "utf8"));
    const playwright = backlog.slices.find((s) => s.id === "slice-a").testRequirements.playwright;
    assert.equal(playwright[0], spec);
    assert.ok(playwright.includes("tests/playwright-ui/playwright.config.ts"));
    assert.ok(playwright.includes("tests/playwright-ui/src/support/auth.ts"));
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});
