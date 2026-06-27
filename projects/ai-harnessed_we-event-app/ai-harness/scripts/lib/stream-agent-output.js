#!/usr/bin/env node
/**
 * Harness adapter: spawn Cursor agent with stream-json, print assistant deltas
 * live to stdout, and append the same text to --outfile for signal parsing.
 *
 * On completion signals (SLICE_DONE, REVIEW_PASS, etc.) or a stream `result`
 * event, waits a short grace period then kills the agent process tree so
 * orphaned shell/MCP children cannot block the Ralph loop.
 *
 * Usage:
 *   node stream-agent-output.js --outfile path [--verbose] \
 *     [--idle-timeout-ms N] [--max-timeout-ms N] \
 *     [--signal-grace-ms N] [--result-grace-ms N] \
 *     [--signals SLICE_DONE,REVIEW_PASS,...] \
 *     -- agent -p ... prompt
 */

const { spawn, execSync } = require("node:child_process");
const { createInterface } = require("node:readline");
const fs = require("node:fs");
const path = require("node:path");

const AGENT_TIMEOUT_EXIT = 124;
const DEFAULT_IDLE_TIMEOUT_MS = 300_000;
const DEFAULT_MAX_TIMEOUT_MS = 3_600_000;
const DEFAULT_SIGNAL_GRACE_MS = 15_000;
const DEFAULT_RESULT_GRACE_MS = 5_000;
const TIMEOUT_POLL_MS = 5_000;
const SIGNAL_SCAN_TAIL_CHARS = 4096;

const DEFAULT_COMPLETION_SIGNALS = [
  "SLICE_DONE",
  "SLICE_BLOCKED",
  "REVIEW_PASS",
  "REVIEW_FAIL",
  "BROWSER_TEST_PASS",
  "BROWSER_TEST_FAIL",
  "TESTGEN_DONE",
  "TESTGEN_BLOCKED",
  "TESTGEN_COMPLETE",
  "COMPLETE",
];

function colorEnabled() {
  if (process.env.NO_COLOR || process.env.AIH_NO_COLOR) return false;
  if (process.env.FORCE_COLOR) return true;
  return Boolean(process.stdout.isTTY || process.stderr.isTTY);
}

function color(code, text) {
  if (!colorEnabled()) return text;
  return `\u001b[${code}m${text}\u001b[0m`;
}

const dim = (text) => color("2", text);
const cyan = (text) => color("36", text);
const yellow = (text) => color("33", text);
const green = (text) => color("32", text);

function writeStderr(line) {
  process.stderr.write(`${line}\n`);
}

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function parseSignalList(raw) {
  if (!raw) return [...DEFAULT_COMPLETION_SIGNALS];
  const signals = raw
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  return signals.length > 0 ? signals : [...DEFAULT_COMPLETION_SIGNALS];
}

function buildCompletionSignalRe(signals) {
  const escaped = signals.map((signal) =>
    signal.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
  );
  return new RegExp(`(?:^|\\n)(${escaped.join("|")})\\b[^\\n]*`, "m");
}

function detectCompletionSignal(text, signalRe) {
  if (!text) return null;
  const tail =
    text.length > SIGNAL_SCAN_TAIL_CHARS
      ? text.slice(-SIGNAL_SCAN_TAIL_CHARS)
      : text;
  const match = signalRe.exec(tail);
  return match ? match[0].trim() : null;
}

function listChildPids(pid) {
  try {
    return execSync(`pgrep -P ${pid}`, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] })
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((value) => Number.parseInt(value, 10))
      .filter((value) => Number.isFinite(value) && value > 0);
  } catch {
    return [];
  }
}

function killProcessTree(pid, signal = "SIGTERM") {
  if (!pid || pid <= 0) return;
  for (const childPid of listChildPids(pid)) {
    killProcessTree(childPid, signal);
  }
  try {
    process.kill(pid, signal);
  } catch {
    // already exited
  }
}

function parseArgs(argv) {
  const options = {
    outfile: "",
    verbose: false,
    idleTimeoutMs: parsePositiveInt(
      process.env.AIH_AGENT_IDLE_TIMEOUT_MS,
      DEFAULT_IDLE_TIMEOUT_MS,
    ),
    maxTimeoutMs: parsePositiveInt(
      process.env.AIH_AGENT_TIMEOUT_MS,
      DEFAULT_MAX_TIMEOUT_MS,
    ),
    signalGraceMs: parsePositiveInt(
      process.env.AIH_AGENT_SIGNAL_GRACE_MS,
      DEFAULT_SIGNAL_GRACE_MS,
    ),
    resultGraceMs: parsePositiveInt(
      process.env.AIH_AGENT_RESULT_GRACE_MS,
      DEFAULT_RESULT_GRACE_MS,
    ),
    signals: [...DEFAULT_COMPLETION_SIGNALS],
    agentArgs: [],
  };

  let i = 0;
  while (i < argv.length) {
    const arg = argv[i];
    if (arg === "--outfile") {
      options.outfile = argv[++i] ?? "";
      i += 1;
      continue;
    }
    if (arg === "--idle-timeout-ms") {
      options.idleTimeoutMs = parsePositiveInt(argv[++i], options.idleTimeoutMs);
      i += 1;
      continue;
    }
    if (arg === "--max-timeout-ms") {
      options.maxTimeoutMs = parsePositiveInt(argv[++i], options.maxTimeoutMs);
      i += 1;
      continue;
    }
    if (arg === "--signal-grace-ms") {
      options.signalGraceMs = parsePositiveInt(argv[++i], options.signalGraceMs);
      i += 1;
      continue;
    }
    if (arg === "--result-grace-ms") {
      options.resultGraceMs = parsePositiveInt(argv[++i], options.resultGraceMs);
      i += 1;
      continue;
    }
    if (arg === "--signals") {
      options.signals = parseSignalList(argv[++i] ?? "");
      i += 1;
      continue;
    }
    if (arg === "--verbose" || arg === "-v") {
      options.verbose = true;
      i += 1;
      continue;
    }
    if (arg === "--") {
      options.agentArgs = argv.slice(i + 1);
      break;
    }
    throw new Error(`Unknown option: ${arg}`);
  }

  if (!options.outfile) {
    throw new Error("--outfile is required");
  }
  if (options.agentArgs.length === 0) {
    throw new Error("agent command required after --");
  }

  options.signalRe = buildCompletionSignalRe(options.signals);
  return options;
}

function extractToolLabel(event) {
  const toolCall = event.tool_call;
  if (!toolCall) return "tool";

  if (toolCall.shellToolCall) {
    const cmd =
      toolCall.shellToolCall.args?.command ??
      toolCall.shellToolCall.result?.success?.command ??
      "shell";
    return `shell: ${cmd}`;
  }
  if (toolCall.readToolCall) return "read file";
  if (toolCall.writeToolCall) return "write file";
  if (toolCall.grepToolCall) return "grep";
  if (toolCall.semanticSearchToolCall) return "search";

  const keys = Object.keys(toolCall);
  return keys[0]?.replace(/ToolCall$/, "") ?? "tool";
}

function extractAssistantText(event) {
  const content = event.message?.content;
  if (!Array.isArray(content)) return "";

  return content
    .filter((block) => block.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("");
}

function writeAssistantText(text, outfileFd) {
  if (!text) return;
  process.stdout.write(text);
  fs.writeSync(outfileFd, text);
}

function writeAssistantDelta(event, state, outfileFd) {
  const text = extractAssistantText(event);
  if (!text) return;

  let delta = text;
  if (state.turnText && text.startsWith(state.turnText)) {
    delta = text.slice(state.turnText.length);
    state.turnText = text;
  } else {
    state.turnText = (state.turnText ?? "") + text;
  }

  writeAssistantText(delta, outfileFd);
  state.outfileText = (state.outfileText ?? "") + delta;
  return detectCompletionSignal(state.outfileText, state.signalRe);
}

function resetAssistantTurn(state) {
  state.turnText = "";
}

function handleStreamEvent(event, state, options, outfileFd, hooks) {
  state.touchActivity();

  switch (event.type) {
    case "system":
      if (options.verbose && event.subtype === "init") {
        writeStderr(
          dim(cyan(`[agent] session=${event.session_id} model=${event.model} cwd=${event.cwd}`)),
        );
      }
      break;

    case "assistant": {
      if (event.timestamp_ms === undefined) {
        resetAssistantTurn(state);
        break;
      }

      const signal = writeAssistantDelta(event, state, outfileFd);
      if (signal) {
        hooks.onCompletionSignal(signal);
      }
      break;
    }

    case "tool_call":
      if (event.subtype === "completed") {
        resetAssistantTurn(state);
      }
      if (!options.verbose) break;
      if (event.subtype === "started") {
        writeStderr(yellow(`[tool] start  ${extractToolLabel(event)}`));
      } else if (event.subtype === "completed") {
        writeStderr(green(`[tool] done   ${extractToolLabel(event)}`));
      }
      break;

    case "result":
      state.result = event;
      if (options.verbose) {
        writeStderr(
          dim(cyan(`[agent] ${event.subtype} duration=${event.duration_ms}ms error=${event.is_error}`)),
        );
      }
      hooks.onResultEvent(event);
      break;

    default:
      break;
  }
}

function timeoutMessage(idleMs, reason) {
  const minutes = Math.round(idleMs / 60_000);
  if (reason === "idle") {
    return `ERROR: Agent timed out after ${idleMs}ms idle (no stream output for ${minutes}m)`;
  }
  return `ERROR: Agent timed out after ${idleMs}ms (${minutes}m max wall time)`;
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (err) {
    console.error(String(err.message ?? err));
    process.exit(1);
  }

  const agentBin = options.agentArgs[0];
  const agentArgs = options.agentArgs.slice(1);
  const state = {
    result: null,
    turnText: "",
    outfileText: "",
    signalRe: options.signalRe,
    lastActivityMs: Date.now(),
    startedMs: Date.now(),
    timedOut: false,
    timeoutReason: "",
    earlyExit: false,
    completionPending: false,
    touchActivity() {
      this.lastActivityMs = Date.now();
    },
  };

  fs.mkdirSync(path.dirname(options.outfile), { recursive: true });
  const outfileFd = fs.openSync(options.outfile, "w");

  const exitCode = await new Promise((resolvePromise, rejectPromise) => {
    let settled = false;
    let idleTimer;
    let maxTimer;
    let shutdownTimer;
    let killTimer;
    let child;

    const finish = (code) => {
      if (settled) return;
      settled = true;
      clearInterval(idleTimer);
      clearInterval(maxTimer);
      clearTimeout(shutdownTimer);
      clearTimeout(killTimer);
      resolvePromise(code);
    };

    const terminateAgentTree = (reason) => {
      if (settled || !child || child.killed) return;
      state.earlyExit = true;
      state.completionPending = true;
      if (options.verbose) {
        writeStderr(yellow(`[agent] terminating process tree (${reason})`));
      }
      killProcessTree(child.pid, "SIGTERM");
      killTimer = setTimeout(() => {
        if (!settled && child && !child.killed) {
          killProcessTree(child.pid, "SIGKILL");
        }
      }, 2000);
      killTimer.unref();
    };

    const scheduleShutdown = (reason, graceMs) => {
      if (settled) return;
      state.completionPending = true;
      const dueAt = Date.now() + graceMs;
      if (shutdownTimer && state.shutdownDueAt && dueAt >= state.shutdownDueAt) {
        return;
      }
      state.shutdownDueAt = dueAt;
      clearTimeout(shutdownTimer);
      if (options.verbose) {
        writeStderr(dim(yellow(`[agent] ${reason} — finishing in ${graceMs}ms`)));
      }
      shutdownTimer = setTimeout(() => {
        terminateAgentTree(reason);
      }, graceMs);
    };

    const hooks = {
      onCompletionSignal(signalLine) {
        scheduleShutdown(`completion signal (${signalLine})`, options.signalGraceMs);
      },
      onResultEvent(event) {
        if (event.is_error) return;
        scheduleShutdown(`result event (${event.subtype})`, options.resultGraceMs);
      },
    };

    const killForTimeout = (reason) => {
      if (settled || !child || child.killed || state.completionPending) return;
      state.timedOut = true;
      state.timeoutReason = reason;
      const ms =
        reason === "idle" ? options.idleTimeoutMs : options.maxTimeoutMs;
      const message = timeoutMessage(ms, reason);
      writeStderr(yellow(message));
      try {
        fs.writeSync(outfileFd, `\n${message}\n`);
      } catch {
        // outfile may already be closed
      }
      terminateAgentTree(`timeout (${reason})`);
    };

    child = spawn(agentBin, agentArgs, {
      stdio: ["ignore", "pipe", "pipe"],
      env: process.env,
    });

    child.stderr.resume();

    idleTimer = setInterval(() => {
      if (state.completionPending) return;
      if (Date.now() - state.lastActivityMs >= options.idleTimeoutMs) {
        killForTimeout("idle");
      }
    }, TIMEOUT_POLL_MS);

    maxTimer = setInterval(() => {
      if (state.completionPending) return;
      if (Date.now() - state.startedMs >= options.maxTimeoutMs) {
        killForTimeout("max");
      }
    }, TIMEOUT_POLL_MS);

    const rl = createInterface({ input: child.stdout, crlfDelay: Infinity });

    rl.on("line", (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;

      state.touchActivity();

      try {
        handleStreamEvent(JSON.parse(trimmed), state, options, outfileFd, hooks);
      } catch {
        writeStderr(yellow(`[warn] non-json line: ${trimmed}`));
      }
    });

    child.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearInterval(idleTimer);
      clearInterval(maxTimer);
      clearTimeout(shutdownTimer);
      clearTimeout(killTimer);
      fs.closeSync(outfileFd);
      rejectPromise(
        new Error(
          `Failed to run "${agentBin}": ${err.message}. Is Cursor CLI installed?`,
        ),
      );
    });

    child.on("close", (code) => {
      clearInterval(idleTimer);
      clearInterval(maxTimer);
      clearTimeout(shutdownTimer);
      clearTimeout(killTimer);
      fs.closeSync(outfileFd);
      if (state.timedOut) {
        finish(AGENT_TIMEOUT_EXIT);
        return;
      }
      if (state.earlyExit && !state.result?.is_error) {
        finish(0);
        return;
      }
      if (state.result?.is_error) {
        finish(2);
        return;
      }
      finish(code ?? 1);
    });
  });

  process.stdout.write("\n");
  process.exit(exitCode);
}

module.exports = {
  AGENT_TIMEOUT_EXIT,
  DEFAULT_COMPLETION_SIGNALS,
  buildCompletionSignalRe,
  detectCompletionSignal,
  killProcessTree,
  listChildPids,
  parseSignalList,
};

if (require.main === module) {
  main().catch((err) => {
    console.error(err.message ?? err);
    process.exit(1);
  });
}
