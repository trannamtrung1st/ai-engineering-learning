import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { UserRole } from "@wecheck/domain";
import { apiFetch } from "@/lib/api-client";
import {
  fetchAuthUser,
  getCachedAuthUser,
  isAuthenticated,
  logoutAuth,
} from "@/lib/auth-session";

vi.mock("@/lib/api-client", () => ({
  apiFetch: vi.fn(),
}));

/** AC-02 / FR-02 / BR-06 / NFR-16 — client auth session helpers */
describe("auth-session (AC-02, FR-02, BR-06, NFR-16)", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    sessionStorage.clear();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, assign: vi.fn() },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("fetchAuthUser returns user on 200 (TC-FR-02-008)", async () => {
    const user = {
      id: "u1",
      institutionalId: "SV2026001",
      displayName: "Sinh viên Nguyễn Văn A",
      email: "student@example.edu.vn",
      role: UserRole.Student,
    };
    vi.mocked(apiFetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: user,
    });

    const result = await fetchAuthUser();
    expect(result).toEqual({ ok: true, user });
    expect(getCachedAuthUser()).toEqual(user);
  });

  it("fetchAuthUser maps SessionExpired from API (TC-NFR-16-006)", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      ok: false,
      status: 401,
      data: { errorCode: "SessionExpired" },
    });

    const result = await fetchAuthUser();
    expect(result).toEqual({ ok: false, errorCode: "SessionExpired" });
  });

  it("fetchAuthUser maps Unauthenticated for other 401 responses (BR-06)", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      ok: false,
      status: 401,
      data: { errorCode: "Unauthenticated" },
    });

    const result = await fetchAuthUser();
    expect(result).toEqual({ ok: false, errorCode: "Unauthenticated" });
  });

  it("fetchAuthUser maps network failures to NetworkError", async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error("offline"));

    const result = await fetchAuthUser();
    expect(result).toEqual({ ok: false, errorCode: "NetworkError" });
  });

  it("isAuthenticated returns true only when /auth/me succeeds", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: {
        id: "u1",
        institutionalId: "SV2026001",
        displayName: "Sinh viên",
        email: "student@example.edu.vn",
        role: UserRole.Student,
      },
    });
    await expect(isAuthenticated()).resolves.toBe(true);

    vi.mocked(apiFetch).mockResolvedValueOnce({
      ok: false,
      status: 401,
      data: { errorCode: "Unauthenticated" },
    });
    await expect(isAuthenticated()).resolves.toBe(false);
  });

  it("logoutAuth POSTs /auth/logout and redirects to /login without returnUrl (AC-02d, FR-02)", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      ok: true,
      status: 204,
      data: undefined,
    });

    await logoutAuth();

    expect(getCachedAuthUser()).toBeNull();
    expect(apiFetch).toHaveBeenCalledWith("/auth/logout", { method: "POST" });
    expect(window.location.assign).toHaveBeenCalledWith("/login");
  });
});
