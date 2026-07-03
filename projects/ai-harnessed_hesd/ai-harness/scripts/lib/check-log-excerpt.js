#!/usr/bin/env node
"use strict";

const fs = require("node:fs");

/**
 * Extract actionable failure text from a computational check log.
 * Used by the harness feedback loop so the next implementer iteration
 * sees assertion details, not only a log file path.
 */
function extractCheckLogFailureExcerpt(logText, maxChars = 8000) {
  if (!logText || typeof logText !== "string") {
    return "";
  }

  const limit = Number.isFinite(maxChars) && maxChars > 0 ? maxChars : 8000;

  const failingTestsIdx = logText.indexOf("✖ failing tests:");
  if (failingTestsIdx !== -1) {
    return logText.slice(failingTestsIdx, failingTestsIdx + limit).trimEnd();
  }

  const playwrightFailed = logText.match(/\n\s*\d+\)\s+.+\n[\s\S]*$/);
  if (playwrightFailed && /failed|Error:|expect\(/.test(playwrightFailed[0])) {
    return playwrightFailed[0].slice(0, limit).trimEnd();
  }

  const tscLines = logText
    .split("\n")
    .filter((line) => /error TS\d+/.test(line) || /^.+\(\d+,\d+\): error/.test(line));
  if (tscLines.length > 0) {
    return tscLines.join("\n").slice(0, limit).trimEnd();
  }

  const eslintLines = logText
    .split("\n")
    .filter((line) => /✖ \d+ problem|error\s+/.test(line) || /\berror\b.*\s{2,}/.test(line));
  if (eslintLines.length > 0) {
    return eslintLines.join("\n").slice(0, limit).trimEnd();
  }

  if (/npm error|Lifecycle script/.test(logText)) {
    const npmIdx = logText.search(/npm error|Lifecycle script/);
    const start = Math.max(0, npmIdx - 1200);
    return logText.slice(start, start + limit).trimEnd();
  }

  const lines = logText.split("\n");
  return lines.slice(-40).join("\n").slice(0, limit).trimEnd();
}

/** Pull integration/e2e test file paths from a Node test runner excerpt. */
function extractFailingTestPaths(excerpt) {
  if (!excerpt) {
    return [];
  }
  const paths = new Set();
  const patterns = [
    /test at ([^\s:]+\.integration\.test\.ts)/g,
    /test at ([^\s:]+\.test\.tsx?)/g,
    /at [^(]+\(([^)]+\.integration\.test\.ts):\d+:\d+\)/g,
    /at [^(]+\(([^)]+\.test\.tsx?):\d+:\d+\)/g,
    /(apps\/api\/src\/[^\s:]+\.integration\.test\.ts)/g,
    /(tests\/e2e\/[^\s:]+\.test\.ts)/g,
  ];
  for (const re of patterns) {
    let match;
    while ((match = re.exec(excerpt)) !== null) {
      let path = match[1].replace(/^\//, "");
      const repoIdx = path.indexOf("/apps/api/src/");
      if (repoIdx !== -1) {
        path = path.slice(repoIdx + 1);
      }
      if (/^src\//.test(path)) {
        paths.add(path);
        paths.add(`apps/api/${path}`);
        continue;
      }
      if (/^apps\//.test(path) || /^tests\//.test(path)) {
        paths.add(path);
      }
    }
  }
  return [...paths];
}

function extractFailingCaseIds(excerpt) {
  if (!excerpt) {
    return [];
  }
  const ids = new Set();
  const re = /\(TC-[A-Z0-9][A-Z0-9-]*\)/g;
  let match;
  while ((match = re.exec(excerpt)) !== null) {
    ids.add(match[0].slice(1, -1));
  }
  return [...ids];
}

function main() {
  const logFile = process.argv[2];
  const maxChars = Number(process.argv[3] || 8000);
  if (!logFile) {
    process.stderr.write("usage: check-log-excerpt.js <log-file> [max-chars]\n");
    process.exit(2);
  }
  const text = fs.readFileSync(logFile, "utf8");
  const excerpt = extractCheckLogFailureExcerpt(text, maxChars);
  if (excerpt) {
    process.stdout.write(excerpt);
  }
}

module.exports = {
  extractCheckLogFailureExcerpt,
  extractFailingTestPaths,
  extractFailingCaseIds,
};

if (require.main === module) {
  main();
}
