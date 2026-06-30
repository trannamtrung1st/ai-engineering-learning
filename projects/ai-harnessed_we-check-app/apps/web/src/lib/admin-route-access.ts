import { UserRole, type UserRole as UserRoleType } from "@wecheck/domain";

/** FR-03 / AC-03c — instructor read-only roster paths under /admin (no import or write) */
export function isInstructorRosterPath(pathname: string): boolean {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  if (normalized === "/admin/rosters") {
    return true;
  }
  const match = /^\/admin\/rosters\/([^/]+)$/.exec(normalized);
  if (!match) {
    return false;
  }
  return match[1] !== "import";
}

export function canAccessAdminShell(role: UserRoleType, pathname: string): boolean {
  if (role === UserRole.TrainingOfficeAdmin) {
    return true;
  }
  if (role === UserRole.Instructor && isInstructorRosterPath(pathname)) {
    return true;
  }
  return false;
}
