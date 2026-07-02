export const STUDENT_AUTH_STORAGE_KEY = "attendly:student-auth";

export interface AuthGateResult {
  redirectTo: string;
  message: string;
}

export function isStudentAuthenticated(): boolean {
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
