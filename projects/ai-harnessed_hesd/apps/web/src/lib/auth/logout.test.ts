import { describe, expect, it, vi, beforeEach } from "vitest";
import { clearStudentAuthentication } from "./auth-gate";
import { performVoluntaryLogout } from "./logout";
import { ACCESS_TOKEN_STORAGE_KEY, clearAccessToken, setAccessToken } from "./session";

const logoutMock = vi.fn().mockResolvedValue({ ok: true });

vi.mock("../api/auth-api.js", () => ({
  logout: () => logoutMock(),
}));

/** Traceability: FR-38 AC-26 BR-24 FLOW-15 */
describe("performVoluntaryLogout (FR-38 AC-26)", () => {
  beforeEach(() => {
    logoutMock.mockClear();
    clearAccessToken();
    clearStudentAuthentication();
  });

  it("TC-FR-38-005: calls logout API then clears access token and student auth flag", async () => {
    setAccessToken("jwt-lecturer");
    sessionStorage.setItem("attendly:student-auth", "1");

    await performVoluntaryLogout();

    expect(logoutMock).toHaveBeenCalledOnce();
    expect(localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem("attendly:student-auth")).toBeNull();
  });

  it("TC-AC-26-007: clears local credentials even when logout API throws", async () => {
    logoutMock.mockRejectedValueOnce(new Error("network"));
    setAccessToken("jwt-student");

    await performVoluntaryLogout();

    expect(localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
  });

  it("skips API call when no token is stored", async () => {
    await performVoluntaryLogout();
    expect(logoutMock).not.toHaveBeenCalled();
  });
});
