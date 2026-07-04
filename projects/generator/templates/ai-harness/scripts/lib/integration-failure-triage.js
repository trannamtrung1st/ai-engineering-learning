#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const {
  extractCheckLogFailureExcerpt,
  extractFailingTestPaths,
  extractFailingCaseIds,
} = require("./check-log-excerpt.js");

/**
 * Map a failing integration test path to the backlog slice that owns it.
 * Mirrors slice_owning_test_path in common.sh.
 */
function resolveOwnerSlice(testPath, backlog) {
  if (!testPath || !backlog || !Array.isArray(backlog.slices)) {
    return null;
  }

  const candidates = [testPath];
  if (!testPath.startsWith("apps/")) {
    candidates.push(`apps/api/src/${testPath.replace(/^src\//, "")}`);
    candidates.push(`apps/api/src/${testPath}`);
  }

  for (const candidate of candidates) {
    for (const slice of backlog.slices) {
      const reqs = slice.testRequirements || {};
      const owned = [
        ...(reqs.integration || []),
        ...(reqs.unit || []),
        ...(reqs.component || []),
      ];
      if (owned.includes(candidate)) {
        return slice.id;
      }
    }
  }
  return null;
}

function detectInfrastructureFailure(logText) {
  if (!logText) {
    return false;
  }
  return /db service not healthy|test stack reset failed|ECONNREFUSED|connection refused|database.*unavailable|cannot connect/i.test(
    logText,
  );
}

function normalizeTestPath(testPath) {
  if (!testPath) {
    return testPath;
  }
  let normalized = testPath.replace(/^\//, "");
  if (normalized.startsWith("apps/api/")) {
    return normalized;
  }
  if (normalized.startsWith("src/")) {
    return `apps/api/${normalized}`;
  }
  return normalized;
}

function classifyIntegrationFailure({
  infrastructure,
  isolatedRunAttempted,
  isolatedRunPass,
}) {
  if (infrastructure) {
    return "infrastructure";
  }
  if (!isolatedRunAttempted) {
    return "unknown";
  }
  if (isolatedRunPass) {
    return "crossSuiteFlake";
  }
  return "reproducible";
}

function buildTriageReport({
  currentSlice,
  logText,
  backlogPath,
  isolatedExitCode = null,
  isolatedRunAttempted = false,
}) {
  const excerpt = extractCheckLogFailureExcerpt(logText || "", 12000);
  const rawPaths = extractFailingTestPaths(excerpt);
  const failingTestPaths = [...new Set(rawPaths.map(normalizeTestPath).filter(Boolean))];
  const failingCaseIds = extractFailingCaseIds(excerpt);
  const infrastructure = detectInfrastructureFailure(logText);

  let backlog = null;
  if (backlogPath && fs.existsSync(backlogPath)) {
    backlog = JSON.parse(fs.readFileSync(backlogPath, "utf8"));
  }

  const ownerCandidates = failingTestPaths
    .map((p) => resolveOwnerSlice(p, backlog))
    .filter(Boolean);
  const ownerSlice = ownerCandidates[0] || null;

  const isolatedRunPass =
    isolatedRunAttempted && isolatedExitCode !== null && isolatedExitCode === 0;
  const classification = classifyIntegrationFailure({
    infrastructure,
    isolatedRunAttempted,
    isolatedRunPass,
  });

  return {
    currentSlice: currentSlice || null,
    failingCaseIds,
    failingTestPaths,
    ownerSlice,
    isolatedRunPass,
    isolatedRunAttempted,
    isolatedExitCode,
    classification,
    investigationRequired: classification !== "infrastructure" && classification !== "unknown",
    prohibitBareRerunResolution: true,
  };
}

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--current-slice") {
      args.currentSlice = argv[++i];
    } else if (arg === "--log") {
      args.logPath = argv[++i];
    } else if (arg === "--backlog") {
      args.backlogPath = argv[++i];
    } else if (arg === "--isolated-exit-code") {
      args.isolatedExitCode = Number(argv[++i]);
    } else if (arg === "--isolated-run-attempted") {
      args.isolatedRunAttempted = argv[++i] !== "false";
    } else if (arg === "--output") {
      args.outputPath = argv[++i];
    } else if (arg === "triage") {
      args.command = "triage";
    } else if (!arg.startsWith("-")) {
      args._.push(arg);
    }
  }
  if (!args.command && args._.length > 0) {
    args.command = args._[0];
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.command !== "triage") {
    process.stderr.write(
      "usage: integration-failure-triage.js triage --current-slice <id> --log <path> --backlog <path> [--isolated-exit-code N] [--isolated-run-attempted true|false] --output <path>\n",
    );
    process.exit(2);
  }

  if (!args.logPath || !fs.existsSync(args.logPath)) {
    process.stderr.write(`integration triage: log file not found: ${args.logPath || ""}\n`);
    process.exit(1);
  }

  const logText = fs.readFileSync(args.logPath, "utf8");
  const report = buildTriageReport({
    currentSlice: args.currentSlice,
    logText,
    backlogPath: args.backlogPath,
    isolatedExitCode: Number.isFinite(args.isolatedExitCode) ? args.isolatedExitCode : null,
    isolatedRunAttempted: args.isolatedRunAttempted !== false,
  });

  const outputPath = args.outputPath;
  if (!outputPath) {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    return;
  }

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`);
}

module.exports = {
  resolveOwnerSlice,
  detectInfrastructureFailure,
  classifyIntegrationFailure,
  buildTriageReport,
  normalizeTestPath,
};

if (require.main === module) {
  main();
}
