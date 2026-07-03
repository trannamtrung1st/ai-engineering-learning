import { describe, expect, it, vi } from "vitest";
import { apiV1BaseUrl } from "./config";

describe("api config (FR-16)", () => {
  it("defaults to same-origin /api/v1 for browser proxy", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    expect(apiV1BaseUrl()).toBe("/api/v1");
  });
});
