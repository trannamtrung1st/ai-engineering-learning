import {
  canAccessAuditLogs,
  canAccessInstitutionReport,
  canAccessSessionControl,
} from "./role-guard.js";
import { getAccessToken } from "./session.js";

export const STUDENT_AUTH_STORAGE_KEY = "attendly:student-auth";

export interface AuthGateResult {
  redirectTo: string;
  message: string;
}

export function isStudentAuthenticated(): boolean {
  if (getAccessToken()) {
    return true;
  }
  if (typeof sessionStorage === "undefined") {
    return false;
  }
  return sessionStorage.getItem(STUDENT_AUTH_STORAGE_KEY) === "1";
}

export function markStudentAuthenticated(): void {
  sessionStorage.setItem(STUDENT_AUTH_STORAGE_KEY, "1");
}

export function clearStudentAuthentication(): void {
  sessionStorage.removeItem(STUDENT_AUTH_STORAGE_KEY);
}

export function requiresCheckInAuth(searchParams: URLSearchParams): boolean {
  const token = searchParams.get("token");
  const outcome = searchParams.get("outcome");
  return Boolean(token) && !outcome;
}

export function buildLoginRedirect(checkInPath: string): AuthGateResult {
  const returnUrl = encodeURIComponent(checkInPath);
  return {
    redirectTo: `/login?returnUrl=${returnUrl}`,
    message: "Đăng nhập để tiếp tục",
  };
}

export function resolveReturnUrl(searchParams: URLSearchParams, fallback = "/"): string {
  const raw = searchParams.get("returnUrl");
  if (!raw) {
    return fallback;
  }

  try {
    const decoded = decodeURIComponent(raw);
    if (decoded.startsWith("/") && !decoded.startsWith("//")) {
      return decoded;
    }
  } catch {
    return fallback;
  }

  return fallback;
}

export function preserveCheckInDeepLink(pathname: string, search: string): string {
  return `${pathname}${search}`;
}

/** Role home when PG-01 has no returnUrl — voluntary logout and neutral entry (TC-UX-COMMON-005). */
export function resolveRoleHomePath(roles: string[]): string {
  if (roles.includes("AcademicAdmin")) {
    return "/admin/terms";
  }

  if (roles.includes("SystemAuditor") && canAccessAuditLogs(roles)) {
    return "/audit/logs";
  }

  if (canAccessSessionControl(roles)) {
    return "/lecturer/sessions";
  }

  if (canAccessInstitutionReport(roles)) {
    return "/reports/attendance";
  }

  if (canAccessAuditLogs(roles)) {
    return "/audit/logs";
  }

  if (roles.includes("Student")) {
    return "/check-in";
  }

  return "/check-in";
}

export function resolvePostLoginPath(
  roles: string[],
  searchParams: URLSearchParams,
): string {
  if (searchParams.get("returnUrl")) {
    return resolveReturnUrl(searchParams, resolveRoleHomePath(roles));
  }

  return resolveRoleHomePath(roles);
}
