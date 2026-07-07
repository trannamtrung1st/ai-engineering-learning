#!/usr/bin/env node
"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  buildCompletionSignalRe,
  detectCompletionSignal,
  parseArgs,
  parseSignalList,
  timeoutMessage,
} = require("./stream-agent-output.js");

test("detectCompletionSignal finds SLICE_DEFER at end of output", () => {
  const re = buildCompletionSignalRe(["SLICE_DEFER", "SLICE_DONE"]);
  const text = "Cannot fix session tests in this slice.\n\nSLICE_DEFER module-session session.integration.test.ts failing";
  assert.equal(
    detectCompletionSignal(text, re),
    "SLICE_DEFER module-session session.integration.test.ts failing",
  );
});

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

test("timeoutMessage distinguishes idle, shell, and max reasons", () => {
  assert.match(timeoutMessage(300_000, "idle"), /idle/);
  assert.match(timeoutMessage(900_000, "shell"), /shell tool in-flight/);
  assert.match(timeoutMessage(3_600_000, "max"), /max wall time/);
});

test("parseArgs caps shell timeout at max timeout", () => {
  const options = parseArgs([
    "--outfile",
    "/tmp/x",
    "--max-timeout-ms",
    "600000",
    "--shell-timeout-ms",
    "900000",
    "--",
    "agent",
    "-p",
    "hi",
  ]);
  assert.equal(options.maxTimeoutMs, 600_000);
  assert.equal(options.shellTimeoutMs, 600_000);
});
