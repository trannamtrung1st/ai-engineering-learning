import { describe, expect, it } from "vitest";
import { detectBrowserSupport, resolveBrowserSupport } from "@/lib/detect-browser-support";

/** NFR-18 — supported browser detection for check-in gate */
describe("detectBrowserSupport (NFR-18)", () => {
  it("accepts iOS Safari user agents", () => {
    const ua =
      "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1";
    expect(detectBrowserSupport(ua).supported).toBe(true);
  });

  it("accepts Android Chrome user agents", () => {
    const ua =
      "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36";
    expect(detectBrowserSupport(ua).supported).toBe(true);
  });

  it("rejects legacy IE user agents", () => {
    const ua = "Mozilla/5.0 (Windows NT 6.1; Trident/7.0; rv:11.0) like Gecko";
    expect(detectBrowserSupport(ua).supported).toBe(false);
  });

  it("forces unsupported via preview override (TC-NFR-18-017)", () => {
    expect(resolveBrowserSupport({ forceUnsupported: true }).supported).toBe(false);
  });
});
