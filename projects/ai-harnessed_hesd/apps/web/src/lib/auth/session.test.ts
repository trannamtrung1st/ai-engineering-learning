import { beforeEach, describe, expect, it } from "vitest";
import {
  ACCESS_TOKEN_STORAGE_KEY,
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "./session";

describe("auth session (FR-15)", () => {
  beforeEach(() => {
    clearAccessToken();
  });

  it("stores and reads bearer access token for API calls", () => {
    expect(getAccessToken()).toBeNull();
    setAccessToken("jwt-token");
    expect(getAccessToken()).toBe("jwt-token");
    expect(localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe("jwt-token");
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });
});
