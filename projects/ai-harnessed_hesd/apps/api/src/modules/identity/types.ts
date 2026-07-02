export const ROLES = [
  "Student",
  "Lecturer",
  "DepartmentAdmin",
  "AcademicAdmin",
  "ITAdmin",
  "SystemAuditor",
] as const;

export type Role = (typeof ROLES)[number];

export const SCOPE_TYPES = [
  "Institution",
  "Faculty",
  "Course",
  "ClassSection",
  "Self",
] as const;

export type ScopeType = (typeof SCOPE_TYPES)[number];

export const RESOURCES = [
  "SessionControl",
  "AttendanceRecord",
  "CheckInAttempt",
  "Enrollment",
  "AttendancePolicy",
  "ReportView",
  "ExportJob",
  "AuditLog",
  "SystemOps",
  "CheckInSubmit",
] as const;

export type Resource = (typeof RESOURCES)[number];

export const ACTIONS = ["read", "create", "update", "delete", "execute"] as const;

export type Action = (typeof ACTIONS)[number];

export interface RoleAssignment {
  role: Role;
  scopeType: ScopeType;
  scopeId: string | null;
}

export interface ActorContext {
  userId: string;
  email: string;
  displayName: string;
  roles: Role[];
  assignments: RoleAssignment[];
}

export interface ScopeContext {
  classSectionId?: string;
  facultyId?: string;
  studentUserId?: string;
  classSessionId?: string;
  institutionId?: string;
}

export type AuthDecision =
  | { allowed: true }
  | { allowed: false; code: "Forbidden" | "OutOfScope"; reason: string };

export interface MeResponse {
  userId: string;
  email: string;
  displayName: string;
  roles: Role[];
  scopes: {
    scopeType: ScopeType;
    scopeId: string | null;
    role: Role;
  }[];
  facultyIds: string[];
  classSectionIds: string[];
}

export interface LoginResponse {
  accessToken: string;
  expiresInSeconds: number;
  roles: Role[];
}
