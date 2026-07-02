#!/usr/bin/env node
"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  extractCheckLogFailureExcerpt,
  extractFailingTestPaths,
  extractFailingCaseIds,
} = require("./check-log-excerpt.js");

const NODE_TEST_LOG = `
▶ session module integration
  ✖ repeat close returns InvalidSessionState (TC-AC-05-007) (1015ms)
✖ session module integration (2932ms)
ℹ tests 118
ℹ fail 1

✖ failing tests:

test at src/modules/session/session.integration.test.ts:25:421
✖ repeat close returns InvalidSessionState (TC-AC-05-007) (1015ms)
  AssertionError [ERR_ASSERTION]: {"error":{"code":"InternalError"}}
  500 !== 201
      at createDraftSession (apps/api/src/modules/session/session.integration.test.ts:195:10)
npm error Lifecycle script \`test:integration\` failed with error:
`;

test("extractCheckLogFailureExcerpt captures node test runner failing block", () => {
  const excerpt = extractCheckLogFailureExcerpt(NODE_TEST_LOG);
  assert.match(excerpt, /✖ failing tests:/);
  assert.match(excerpt, /repeat close returns InvalidSessionState/);
  assert.match(excerpt, /500 !== 201/);
});

test("extractFailingTestPaths finds integration test files", () => {
  const excerpt = extractCheckLogFailureExcerpt(NODE_TEST_LOG);
  const paths = extractFailingTestPaths(excerpt);
  assert.ok(paths.some((p) => p.includes("session.integration.test.ts")));
});

test("extractFailingCaseIds finds TC tags", () => {
  const excerpt = extractCheckLogFailureExcerpt(NODE_TEST_LOG);
  assert.deepEqual(extractFailingCaseIds(excerpt), ["TC-AC-05-007"]);
});

test("extractCheckLogFailureExcerpt falls back to tail for unknown logs", () => {
  const log = Array.from({ length: 60 }, (_, i) => `line ${i}`).join("\n");
  const excerpt = extractCheckLogFailureExcerpt(log, 8000);
  assert.match(excerpt, /line 59/);
  assert.doesNotMatch(excerpt, /line 0\n/);
});
