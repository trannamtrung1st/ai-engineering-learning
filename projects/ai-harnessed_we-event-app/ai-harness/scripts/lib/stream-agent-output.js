#!/usr/bin/env node
/**
 * Harness adapter: spawn Cursor agent with stream-json, print assistant deltas
 * live to stdout, and append the same text to --outfile for signal parsing.
 *
 * Usage:
 *   node stream-agent-output.js --outfile path [--verbose] -- agent -p ... prompt
 */

const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const fs = require("node:fs");
const path = require("node:path");

function parseArgs(argv) {
  const options = {
    outfile: "",
    verbose: false,
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

  // stream-partial-output may send cumulative text; emit only the new suffix.
  let delta = text;
  if (state.assistantText && text.startsWith(state.assistantText)) {
    delta = text.slice(state.assistantText.length);
    state.assistantText = text;
  } else {
    state.assistantText = (state.assistantText ?? "") + text;
  }

  writeAssistantText(delta, outfileFd);
}

function handleStreamEvent(event, state, options, outfileFd) {
  switch (event.type) {
    case "system":
      if (options.verbose && event.subtype === "init") {
        process.stderr.write(
          `[agent] session=${event.session_id} model=${event.model} cwd=${event.cwd}\n`,
        );
      }
      break;

    case "assistant": {
      // Partial deltas include timestamp_ms; the final cumulative message does not.
      if (event.timestamp_ms === undefined) {
        state.assistantText = "";
        break;
      }

      writeAssistantDelta(event, state, outfileFd);
      break;
    }

    case "tool_call":
      if (!options.verbose) break;
      if (event.subtype === "started") {
        process.stderr.write(`[tool] start  ${extractToolLabel(event)}\n`);
      } else if (event.subtype === "completed") {
        process.stderr.write(`[tool] done   ${extractToolLabel(event)}\n`);
      }
      break;

    case "result":
      state.result = event;
      if (options.verbose) {
        process.stderr.write(
          `[agent] ${event.subtype} duration=${event.duration_ms}ms error=${event.is_error}\n`,
        );
      }
      break;

    default:
      break;
  }
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
  const state = { result: null, assistantText: "" };

  fs.mkdirSync(path.dirname(options.outfile), { recursive: true });
  const outfileFd = fs.openSync(options.outfile, "w");

  const exitCode = await new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(agentBin, agentArgs, {
      stdio: ["ignore", "pipe", "pipe"],
      env: process.env,
    });

    // Ignore agent stderr — it mirrors assistant text. Tool activity comes from stdout JSON.
    child.stderr.resume();

    const rl = createInterface({ input: child.stdout, crlfDelay: Infinity });

    rl.on("line", (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;

      try {
        handleStreamEvent(JSON.parse(trimmed), state, options, outfileFd);
      } catch {
        process.stderr.write(`[warn] non-json line: ${trimmed}\n`);
      }
    });

    child.on("error", (err) => {
      fs.closeSync(outfileFd);
      rejectPromise(
        new Error(
          `Failed to run "${agentBin}": ${err.message}. Is Cursor CLI installed?`,
        ),
      );
    });

    child.on("close", (code) => {
      fs.closeSync(outfileFd);
      if (state.result?.is_error) {
        resolvePromise(2);
        return;
      }
      resolvePromise(code ?? 1);
    });
  });

  process.stdout.write("\n");
  process.exit(exitCode);
}

main().catch((err) => {
  console.error(err.message ?? err);
  process.exit(1);
});
