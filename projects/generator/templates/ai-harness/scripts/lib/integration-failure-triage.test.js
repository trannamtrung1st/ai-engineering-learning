#!/usr/bin/env node
"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
  extractCheckLogFailureExcerpt,
  extractFailingTestPaths,
  extractFailingCaseIds,
} = require("./check-log-excerpt.js");
const {
  resolveOwnerSlice,
  detectInfrastructureFailure,
  classifyIntegrationFailure,
  buildTriageReport,
  normalizeTestPath,
} = require("./integration-failure-triage.js");

const FIXTURE_LOG = `
 FAIL  src/modules/academic-structure/academic-structure.integration.test.ts > academic structure integration — FR-01 FR-04 FR-06 BR-06 AC-07 > TC-FR-06-009 — class-sessions pagination invariants for assigned section
AssertionError: expected 10 to be 9 // Object.is equality
 ❯ src/modules/academic-structure/academic-structure.integration.test.ts:435:48
`;

const BACKLOG_FIXTURE = {
  slices: [
    {
      id: "module-academic-structure",
      testRequirements: {
        integration: [
          "apps/api/src/modules/academic-structure/academic-structure.integration.test.ts",
        ],
      },
    },
    {
      id: "web-design-system-shell",
      testRequirements: {
        component: ["apps/web/src/components/foo/foo.test.tsx"],
      },
    },
  ],
};

test("parse excerpt from academic-structure integration failure log", () => {
  const excerpt = extractCheckLogFailureExcerpt(FIXTURE_LOG);
  const paths = extractFailingTestPaths(excerpt);
  assert.ok(
    paths.some((p) => p.includes("academic-structure.integration.test.ts")),
  );
  assert.deepEqual(extractFailingCaseIds(excerpt), ["TC-FR-06-009"]);
});

test("normalizeTestPath maps src/ paths to apps/api prefix", () => {
  assert.equal(
    normalizeTestPath("src/modules/academic-structure/academic-structure.integration.test.ts"),
    "apps/api/src/modules/academic-structure/academic-structure.integration.test.ts",
  );
});

test("resolveOwnerSlice maps academic-structure test to module-academic-structure", () => {
  const owner = resolveOwnerSlice(
    "apps/api/src/modules/academic-structure/academic-structure.integration.test.ts",
    BACKLOG_FIXTURE,
  );
  assert.equal(owner, "module-academic-structure");
});

test("classifyIntegrationFailure detects crossSuiteFlake when isolated pass", () => {
  assert.equal(
    classifyIntegrationFailure({
      infrastructure: false,
      isolatedRunAttempted: true,
      isolatedRunPass: true,
    }),
    "crossSuiteFlake",
  );
});

test("classifyIntegrationFailure detects reproducible when isolated fail", () => {
  assert.equal(
    classifyIntegrationFailure({
      infrastructure: false,
      isolatedRunAttempted: true,
      isolatedRunPass: false,
    }),
    "reproducible",
  );
});

test("buildTriageReport classifies crossSuiteFlake with mocked isolated pass", () => {
  const backlogFile = path.join(__dirname, ".triage-test-backlog.json");
  fs.writeFileSync(backlogFile, `${JSON.stringify(BACKLOG_FIXTURE, null, 2)}\n`);
  try {
    const fullReport = buildTriageReport({
      currentSlice: "web-design-system-shell",
      logText: FIXTURE_LOG,
      backlogPath: backlogFile,
      isolatedExitCode: 0,
      isolatedRunAttempted: true,
    });

    assert.equal(fullReport.classification, "crossSuiteFlake");
    assert.equal(fullReport.isolatedRunPass, true);
    assert.equal(fullReport.failingCaseIds[0], "TC-FR-06-009");
    assert.equal(fullReport.ownerSlice, "module-academic-structure");
    assert.equal(fullReport.investigationRequired, true);
  } finally {
    fs.unlinkSync(backlogFile);
  }
});

test("detectInfrastructureFailure flags stack errors", () => {
  assert.equal(detectInfrastructureFailure("db service not healthy"), true);
  assert.equal(detectInfrastructureFailure("expected 10 to be 9"), false);
});

test("buildTriageReport from real gate log fixture when present", () => {
  const logPath = path.join(
    __dirname,
    "..",
    "..",
    "generated",
    "runs",
    "20260703T214911Z-check-test-integration.log",
  );
  if (!fs.existsSync(logPath)) {
    return;
  }
  const logText = fs.readFileSync(logPath, "utf8");
  const report = buildTriageReport({
    currentSlice: "web-design-system-shell",
    logText,
    backlogPath: path.join(__dirname, "..", "..", "whole-app-backlog.json"),
    isolatedExitCode: 0,
    isolatedRunAttempted: true,
  });
  assert.equal(report.classification, "crossSuiteFlake");
  assert.equal(report.ownerSlice, "module-academic-structure");
  assert.ok(report.failingCaseIds.includes("TC-FR-06-009"));
});
