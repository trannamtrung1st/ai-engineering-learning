import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

import { allDomainStatuses, statusTokenMap } from "./status-tokens.js";

const globalsCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../app/globals.css"),
  "utf8",
);

describe("semantic status tokens", () => {
  it("maps every domain status to CSS variable pairs", () => {
    for (const status of allDomainStatuses) {
      const tokens = statusTokenMap[status];
      assert.match(tokens.bg, /^var\(--color-status-/);
      assert.match(tokens.fg, /^var\(--color-status-.*-fg\)$/);
      assert.ok(tokens.label.length > 0);
    }
  });

  it("declares matching CSS variables in globals.css", () => {
    for (const status of allDomainStatuses) {
      const tokens = statusTokenMap[status];
      const bgVar = tokens.bg.slice(4, -1);
      const fgVar = tokens.fg.slice(4, -1);
      assert.match(globalsCss, new RegExp(`${bgVar}:`));
      assert.match(globalsCss, new RegExp(`${fgVar}:`));
      assert.match(globalsCss, new RegExp(`data-domain-status="${status}"`));
    }
  });
});
