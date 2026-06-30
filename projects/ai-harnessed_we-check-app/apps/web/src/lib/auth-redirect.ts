import { UserRole, type UserRole as UserRoleType } from "@wecheck/domain";

/** Default landing routes per docs/ui-ux/09-page-list.md §1 */
export const ROLE_HOME: Record<UserRoleType, string> = {
  [UserRole.Student]: "/check-in",
  [UserRole.Instructor]: "/sessions",
  [UserRole.TrainingOfficeAdmin]: "/admin",
};

/** VAL-09 — relative returnUrl only; blocks open redirects and login loops */
export function isSafeReturnUrl(path: string | null | undefined): path is string {
  if (!path) return false;
  if (!path.startsWith("/") || path.startsWith("//")) return false;
  if (path.length > 512) return false;
  if (path === "/login" || path.startsWith("/login?")) return false;
  return true;
}

export function getRoleHome(role: UserRoleType): string {
  return ROLE_HOME[role] ?? "/";
}

export function resolvePostLoginRedirect(
  role: UserRoleType,
  options?: { returnUrl?: string | null; redirectTo?: string | null },
): string {
  const candidate = options?.redirectTo ?? options?.returnUrl ?? null;
  if (isSafeReturnUrl(candidate)) {
    return candidate;
  }
  return getRoleHome(role);
}

export function loginReturnUrl(
  returnPath: string,
  options?: { sessionExpired?: boolean },
): string {
  const params = new URLSearchParams();
  params.set("returnUrl", returnPath);
  if (options?.sessionExpired) {
    params.set("sessionExpired", "1");
  }
  return `/login?${params.toString()}`;
}

export function currentPathWithSearch(location: {
  pathname: string;
  search: string;
}): string {
  return `${location.pathname}${location.search}`;
}
