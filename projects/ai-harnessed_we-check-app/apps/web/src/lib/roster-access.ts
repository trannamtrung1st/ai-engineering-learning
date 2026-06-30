import { UserRole, type UserRole as UserRoleType } from "@wecheck/domain";

/** FR-03 / AC-03 — roster listing RBAC (import remains admin-only) */
export function canViewRoster(role: UserRoleType): boolean {
  return role === UserRole.TrainingOfficeAdmin || role === UserRole.Instructor;
}

export function canImportRoster(role: UserRoleType): boolean {
  return role === UserRole.TrainingOfficeAdmin;
}
