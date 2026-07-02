import type { UserRole } from "@wecheck/domain";
import { apiFetch } from "@/lib/api-client";

export interface AuthUser {
  id: string;
  institutionalId: string;
  displayName: string;
  email: string;
  role: UserRole;
}

export type AuthSessionErrorCode = "Unauthenticated" | "SessionExpired" | "NetworkError";

export type AuthSessionResult =
  | { ok: true; user: AuthUser }
  | { ok: false; errorCode: AuthSessionErrorCode };

const AUTH_USER_CACHE_KEY = "wecheck-auth-user";

export function getCachedAuthUser(): AuthUser | null {
  try {
    const raw = sessionStorage.getItem(AUTH_USER_CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function setCachedAuthUser(user: AuthUser | null): void {
  try {
    if (user) {
      sessionStorage.setItem(AUTH_USER_CACHE_KEY, JSON.stringify(user));
    } else {
      sessionStorage.removeItem(AUTH_USER_CACHE_KEY);
    }
  } catch {
    // ignore storage failures (private mode, quota)
  }
}

export async function fetchAuthUser(): Promise<AuthSessionResult> {
  try {
    const res = await apiFetch<AuthUser>("/auth/me");
    if (res.ok) {
      setCachedAuthUser(res.data);
      return { ok: true, user: res.data };
    }
    if (res.data.errorCode === "SessionExpired") {
      setCachedAuthUser(null);
      return { ok: false, errorCode: "SessionExpired" };
    }
    setCachedAuthUser(null);
    return { ok: false, errorCode: "Unauthenticated" };
  } catch {
    return { ok: false, errorCode: "NetworkError" };
  }
}

/** Prime session cache after login before full-page redirect */
export async function primeAuthSessionCache(): Promise<void> {
  await fetchAuthUser();
}

export async function isAuthenticated(): Promise<boolean> {
  const result = await fetchAuthUser();
  return result.ok;
}

/** FR-02 / AC-02d — revoke session and land on login without returnUrl */
export async function logoutAuth(): Promise<void> {
  setCachedAuthUser(null);
  await apiFetch("/auth/logout", { method: "POST" });
  window.location.assign("/login");
}
