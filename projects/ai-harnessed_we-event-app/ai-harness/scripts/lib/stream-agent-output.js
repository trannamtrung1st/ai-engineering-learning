#!/usr/bin/env node
/**
 * Harness adapter: spawn Cursor agent with stream-json, print assistant deltas
 * live to stdout, and append the same text to --outfile for signal parsing.
 *
 * Usage:
 *   node stream-agent-output.js --outfile path [--verbose] \
 *     [--idle-timeout-ms N] [--max-timeout-ms N] -- agent -p ... prompt
 */

const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const fs = require("node:fs");
const path = require("node:path");

const AGENT_TIMEOUT_EXIT = 124;
const DEFAULT_IDLE_TIMEOUT_MS = 300_000;
const DEFAULT_MAX_TIMEOUT_MS = 3_600_000;
const TIMEOUT_POLL_MS = 5_000;

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
}

function resetAssistantTurn(state) {
  state.turnText = "";
}

function handleStreamEvent(event, state, options, outfileFd) {
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

      writeAssistantDelta(event, state, outfileFd);
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
    lastActivityMs: Date.now(),
    startedMs: Date.now(),
    timedOut: false,
    timeoutReason: "",
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
    let child;

    const finish = (code) => {
      if (settled) return;
      settled = true;
      clearInterval(idleTimer);
      clearInterval(maxTimer);
      resolvePromise(code);
    };

    const killForTimeout = (reason) => {
      if (settled || !child || child.killed) return;
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
      child.kill("SIGTERM");
      setTimeout(() => {
        if (child && !child.killed) {
          child.kill("SIGKILL");
        }
      }, 2000).unref();
    };

    child = spawn(agentBin, agentArgs, {
      stdio: ["ignore", "pipe", "pipe"],
      env: process.env,
    });

    child.stderr.resume();

    idleTimer = setInterval(() => {
      if (Date.now() - state.lastActivityMs >= options.idleTimeoutMs) {
        killForTimeout("idle");
      }
    }, TIMEOUT_POLL_MS);

    maxTimer = setInterval(() => {
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
        handleStreamEvent(JSON.parse(trimmed), state, options, outfileFd);
      } catch {
        writeStderr(yellow(`[warn] non-json line: ${trimmed}`));
      }
    });

    child.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearInterval(idleTimer);
      clearInterval(maxTimer);
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
      fs.closeSync(outfileFd);
      if (state.timedOut) {
        finish(AGENT_TIMEOUT_EXIT);
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

main().catch((err) => {
  console.error(err.message ?? err);
  process.exit(1);
});
