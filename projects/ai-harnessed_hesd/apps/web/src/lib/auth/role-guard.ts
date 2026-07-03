export type StaffReportRole =
  | "Lecturer"
  | "DepartmentAdmin"
  | "AcademicAdmin"
  | "SystemAuditor";

const STAFF_REPORT_ROLES = new Set<StaffReportRole>([
  "Lecturer",
  "DepartmentAdmin",
  "AcademicAdmin",
  "SystemAuditor",
]);

export function canAccessInstitutionReport(roles: string[]): boolean {
  return roles.some((role) => STAFF_REPORT_ROLES.has(role as StaffReportRole));
}

export function canExecuteExport(roles: string[]): boolean {
  return roles.some((role) =>
    (["Lecturer", "DepartmentAdmin", "AcademicAdmin"] as const).includes(
      role as "Lecturer" | "DepartmentAdmin" | "AcademicAdmin",
    ),
  );
}

export function canAccessSessionControl(roles: string[]): boolean {
  return roles.some((role) =>
    (["Lecturer", "AcademicAdmin"] as const).includes(
      role as "Lecturer" | "AcademicAdmin",
    ),
  );
}

export function isStudentOnly(roles: string[]): boolean {
  return roles.length === 1 && roles[0] === "Student";
}

export function isAcademicAdmin(roles: string[]): boolean {
  return roles.includes("AcademicAdmin");
}

const AUDIT_LOG_ROLES = new Set<StaffReportRole | "ITAdmin">([
  "Lecturer",
  "DepartmentAdmin",
  "AcademicAdmin",
  "SystemAuditor",
  "ITAdmin",
]);

export function canAccessAuditLogs(roles: string[]): boolean {
  return roles.some((role) => AUDIT_LOG_ROLES.has(role as StaffReportRole | "ITAdmin"));
}

export function isSystemAuditor(roles: string[]): boolean {
  return roles.includes("SystemAuditor");
}

export function isReadOnlyStaffRole(roles: string[]): boolean {
  return isSystemAuditor(roles);
}

export interface StaffNavLink {
  to: string;
  label: string;
}

/** Role home link — always first in SidebarNav per design-system/sidebars.md */
export function resolveStaffHomeNav(roles: string[]): StaffNavLink {
  if (
    !canAccessSessionControl(roles) &&
    canAccessAuditLogs(roles) &&
    roles.some((role) => role === "ITAdmin" || role === "SystemAuditor")
  ) {
    return { to: "/audit/logs", label: "Nhật ký kiểm toán" };
  }

  return { to: "/lecturer/sessions", label: "Phiên học" };
}
