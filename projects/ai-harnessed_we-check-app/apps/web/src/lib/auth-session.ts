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

export async function fetchAuthUser(): Promise<AuthSessionResult> {
  try {
    const res = await apiFetch<AuthUser>("/auth/me");
    if (res.ok) {
      return { ok: true, user: res.data };
    }
    if (res.data.errorCode === "SessionExpired") {
      return { ok: false, errorCode: "SessionExpired" };
    }
    return { ok: false, errorCode: "Unauthenticated" };
  } catch {
    return { ok: false, errorCode: "NetworkError" };
  }
}

export async function isAuthenticated(): Promise<boolean> {
  const result = await fetchAuthUser();
  return result.ok;
}
