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

export function isStudentOnly(roles: string[]): boolean {
  return roles.length === 1 && roles[0] === "Student";
}
