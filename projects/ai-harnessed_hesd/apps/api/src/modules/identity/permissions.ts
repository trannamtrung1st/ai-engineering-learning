import type { Action, Resource, Role } from "./types.js";

/** Capability matrix — docs/technical/01-roles-permissions.md §3.2 */
type PermissionEffect = "allow" | "deny" | "scoped";

const MATRIX: Record<Resource, Partial<Record<Action, Partial<Record<Role, PermissionEffect>>>>> = {
  SessionControl: {
    execute: {
      Lecturer: "scoped",
      AcademicAdmin: "allow",
    },
  },
  AttendanceRecord: {
    read: {
      Student: "scoped",
      Lecturer: "scoped",
      DepartmentAdmin: "scoped",
      AcademicAdmin: "allow",
      SystemAuditor: "scoped",
    },
    update: {
      Lecturer: "scoped",
      DepartmentAdmin: "scoped",
      AcademicAdmin: "allow",
    },
  },
  CheckInAttempt: {
    read: {
      Student: "scoped",
      Lecturer: "scoped",
      DepartmentAdmin: "scoped",
      AcademicAdmin: "allow",
      SystemAuditor: "scoped",
    },
  },
  Enrollment: {
    read: {
      Student: "scoped",
      Lecturer: "scoped",
      DepartmentAdmin: "scoped",
      AcademicAdmin: "allow",
      SystemAuditor: "scoped",
    },
    create: { AcademicAdmin: "allow", DepartmentAdmin: "scoped" },
    update: { AcademicAdmin: "allow", DepartmentAdmin: "scoped" },
  },
  AttendancePolicy: {
    read: {
      Lecturer: "allow",
      DepartmentAdmin: "scoped",
      AcademicAdmin: "allow",
      SystemAuditor: "scoped",
    },
    update: { AcademicAdmin: "allow" },
  },
  ReportView: {
    read: {
      Lecturer: "scoped",
      DepartmentAdmin: "scoped",
      AcademicAdmin: "allow",
      SystemAuditor: "scoped",
    },
  },
  ExportJob: {
    execute: {
      Lecturer: "scoped",
      DepartmentAdmin: "scoped",
      AcademicAdmin: "allow",
    },
  },
  AuditLog: {
    read: {
      Lecturer: "scoped",
      DepartmentAdmin: "scoped",
      AcademicAdmin: "allow",
      ITAdmin: "scoped",
      SystemAuditor: "scoped",
    },
  },
  SystemOps: {
    execute: { ITAdmin: "allow", AcademicAdmin: "scoped" },
  },
  CheckInSubmit: {
    execute: { Student: "scoped" },
  },
};

export function capabilityForRole(
  role: Role,
  resource: Resource,
  action: Action,
): PermissionEffect {
  return MATRIX[resource]?.[action]?.[role] ?? "deny";
}

export function rolesWithCapability(resource: Resource, action: Action): Role[] {
  const row = MATRIX[resource]?.[action];
  if (!row) return [];
  return (Object.entries(row) as [Role, PermissionEffect][])
    .filter(([, effect]) => effect !== "deny")
    .map(([role]) => role);
}

export function isReadOnlyRole(role: Role): boolean {
  return role === "SystemAuditor";
}
