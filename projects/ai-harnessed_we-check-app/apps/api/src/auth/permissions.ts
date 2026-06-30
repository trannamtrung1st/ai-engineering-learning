import { UserRole } from "@wecheck/domain";
import type { UserRole as UserRoleType } from "@wecheck/domain";

/** Permission vocabulary per docs/technical/01-roles-permissions.md §2.1 */
export const Permission = {
  UserRead: "user:read",
  UserWrite: "user:write",
  RosterRead: "roster:read",
  RosterWrite: "roster:write",
  SessionRead: "session:read",
  SessionWrite: "session:write",
  QrDisplay: "qr:display",
  CheckinSubmit: "checkin:submit",
  AttendanceRead: "attendance:read",
  AttendanceWrite: "attendance:write",
  ReportRead: "report:read",
  ReportExport: "report:export",
  AuditRead: "audit:read",
  NotificationRead: "notification:read",
  PolicyWrite: "policy:write",
} as const;

export type Permission = (typeof Permission)[keyof typeof Permission];

/** Role-to-permission matrix — deny by default per §2.2 */
const ROLE_PERMISSIONS: Readonly<Record<UserRoleType, ReadonlySet<Permission>>> =
  {
    [UserRole.Student]: new Set([
      Permission.UserRead,
      Permission.CheckinSubmit,
      Permission.AttendanceRead,
      Permission.NotificationRead,
    ]),
    [UserRole.Instructor]: new Set([
      Permission.UserRead,
      Permission.RosterRead,
      Permission.SessionRead,
      Permission.SessionWrite,
      Permission.QrDisplay,
      Permission.AttendanceRead,
      Permission.AttendanceWrite,
      Permission.ReportRead,
      Permission.NotificationRead,
    ]),
    [UserRole.TrainingOfficeAdmin]: new Set([
      Permission.UserRead,
      Permission.UserWrite,
      Permission.RosterRead,
      Permission.RosterWrite,
      Permission.SessionRead,
      Permission.AttendanceRead,
      Permission.AttendanceWrite,
      Permission.ReportRead,
      Permission.ReportExport,
      Permission.AuditRead,
      Permission.NotificationRead,
      Permission.PolicyWrite,
    ]),
  };

export function roleHasPermission(
  role: UserRoleType,
  permission: Permission,
): boolean {
  return ROLE_PERMISSIONS[role]?.has(permission) ?? false;
}

export function getPermissionsForRole(role: UserRoleType): Permission[] {
  return [...(ROLE_PERMISSIONS[role] ?? [])];
}

/** Default SPA landing routes per docs/ui-ux/09-page-list.md §1 */
export const ROLE_HOME_PATHS: Readonly<Record<UserRoleType, string>> = {
  [UserRole.Student]: "/check-in",
  [UserRole.Instructor]: "/sessions",
  [UserRole.TrainingOfficeAdmin]: "/admin",
};

export function getRoleHomePath(role: UserRoleType): string {
  return ROLE_HOME_PATHS[role] ?? "/";
}

export function assertPermission(
  role: UserRoleType,
  permission: Permission,
): boolean {
  return roleHasPermission(role, permission);
}

/** Denied permission probes for RBAC negative matrix (NFR-11). */
export const RBAC_DENIED_MATRIX: Readonly<
  Record<UserRoleType, readonly Permission[]>
> = {
  [UserRole.Student]: [
    Permission.UserWrite,
    Permission.RosterWrite,
    Permission.SessionWrite,
    Permission.SessionRead,
    Permission.QrDisplay,
    Permission.ReportRead,
    Permission.ReportExport,
    Permission.PolicyWrite,
    Permission.AuditRead,
  ],
  [UserRole.Instructor]: [
    Permission.CheckinSubmit,
    Permission.ReportExport,
    Permission.UserWrite,
    Permission.RosterWrite,
    Permission.PolicyWrite,
    Permission.AuditRead,
  ],
  [UserRole.TrainingOfficeAdmin]: [
    Permission.CheckinSubmit,
    Permission.QrDisplay,
  ],
};
