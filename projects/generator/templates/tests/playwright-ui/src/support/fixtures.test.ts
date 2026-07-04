import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { loginViaApi } from "./auth.js";
import { API_BASE_URL, DEFAULT_PASSWORD, WEB_BASE_URL } from "./constants.js";

const WORKSPACE_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../..");

describe("playwright-ui support fixtures", () => {
  it("exports preview stack URLs aligned with harness defaults", () => {
    expect(WEB_BASE_URL).toMatch(/^https?:\/\//);
    expect(API_BASE_URL).toMatch(/\/api\/v1$/);
    expect(DEFAULT_PASSWORD).toBeTruthy();
  });

  it("exposes loginViaApi helper for browser regression auth", () => {
    expect(typeof loginViaApi).toBe("function");
  });

  it("configures playwright scenarios directory and desktop/mobile projects", () => {
    const configSource = readFileSync(
      resolve(WORKSPACE_ROOT, "playwright.config.ts"),
      "utf8",
    );
    expect(configSource).toContain('testDir: "./scenarios"');
    expect(configSource).toContain('name: "chromium"');
    expect(configSource).toContain('name: "mobile"');
    expect(configSource).toContain("http://localhost:3007");
  });

  it("declares test:playwright-ui script in workspace package", () => {
    const pkg = JSON.parse(
      readFileSync(resolve(WORKSPACE_ROOT, "package.json"), "utf8"),
    ) as { scripts: Record<string, string> };
    expect(pkg.scripts["test:playwright-ui"]).toContain("playwright test");
  });
});
