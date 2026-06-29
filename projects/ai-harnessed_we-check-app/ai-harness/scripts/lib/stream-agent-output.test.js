#!/usr/bin/env node
"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  buildCompletionSignalRe,
  detectCompletionSignal,
  parseSignalList,
} = require("./stream-agent-output.js");

test("detectCompletionSignal finds SLICE_DONE at end of output", () => {
  const re = buildCompletionSignalRe(["SLICE_DONE", "SLICE_BLOCKED"]);
  const text = "All checks pass.\n\nSLICE_DONE web-design-system-shell";
  assert.equal(detectCompletionSignal(text, re), "SLICE_DONE web-design-system-shell");
});

test("detectCompletionSignal ignores partial prefix matches", () => {
  const re = buildCompletionSignalRe(["SLICE_DONE"]);
  assert.equal(detectCompletionSignal("Not SLICE_DONEYET", re), null);
});

test("detectCompletionSignal scans only recent tail", () => {
  const re = buildCompletionSignalRe(["REVIEW_PASS"]);
  const padding = "x".repeat(5000);
  const text = `${padding}\nREVIEW_PASS`;
  assert.equal(detectCompletionSignal(text, re), "REVIEW_PASS");
});

test("parseSignalList falls back to defaults when empty", () => {
  const signals = parseSignalList("");
  assert.ok(signals.includes("SLICE_DONE"));
  assert.ok(signals.includes("BROWSER_TEST_PASS"));
});
