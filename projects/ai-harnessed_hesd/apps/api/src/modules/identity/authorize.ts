import { capabilityForRole, isReadOnlyRole } from "./permissions.js";
import type {
  Action,
  ActorContext,
  AuthDecision,
  Resource,
  Role,
  RoleAssignment,
  ScopeContext,
} from "./types.js";

export interface ScopeBindings {
  classSectionFacultyId?: string;
  classSectionIdsForFaculty?: string[];
  lecturerClassSectionIds?: string[];
}

function assignmentMatchesScope(
  assignment: RoleAssignment,
  target: ScopeContext,
  bindings: ScopeBindings,
): boolean {
  const { scopeType, scopeId } = assignment;

  if (scopeType === "Institution") {
    return true;
  }

  if (scopeType === "Self") {
    if (target.studentUserId && scopeId) {
      return target.studentUserId === scopeId;
    }
    return false;
  }

  if (scopeType === "ClassSection") {
    if (target.classSectionId && scopeId) {
      return target.classSectionId === scopeId;
    }
    if (target.classSessionId && bindings.lecturerClassSectionIds?.length) {
      return bindings.lecturerClassSectionIds.includes(target.classSectionId ?? "");
    }
    return false;
  }

  if (scopeType === "Faculty") {
    if (target.facultyId && scopeId) {
      return target.facultyId === scopeId;
    }
    if (target.classSectionId && bindings.classSectionFacultyId && scopeId) {
      return bindings.classSectionFacultyId === scopeId;
    }
    if (target.classSectionId && bindings.classSectionIdsForFaculty?.length && scopeId) {
      return bindings.classSectionIdsForFaculty.includes(target.classSectionId);
    }
    return false;
  }

  return false;
}

function hasScopedCapability(
  role: Role,
  resource: Resource,
  action: Action,
): boolean {
  const effect = capabilityForRole(role, resource, action);
  return effect === "scoped" || effect === "allow";
}

export function authorize(
  actor: ActorContext,
  resource: Resource,
  action: Action,
  target: ScopeContext,
  bindings: ScopeBindings = {},
): AuthDecision {
  if (action !== "read" && actor.roles.some(isReadOnlyRole)) {
    return { allowed: false, code: "Forbidden", reason: "Read-only auditor role" };
  }

  let rolePermitsAction = false;
  let rolePermitsScope = false;

  for (const assignment of actor.assignments) {
    const effect = capabilityForRole(assignment.role, resource, action);
    if (effect === "deny") continue;

    rolePermitsAction = true;

    if (effect === "allow") {
      rolePermitsScope = true;
      break;
    }

    if (effect === "scoped" && assignmentMatchesScope(assignment, target, bindings)) {
      rolePermitsScope = true;
      break;
    }
  }

  if (!rolePermitsAction) {
    return {
      allowed: false,
      code: "Forbidden",
      reason: `Role not permitted for ${resource}.${action}`,
    };
  }

  if (!rolePermitsScope) {
    return {
      allowed: false,
      code: "OutOfScope",
      reason: "Target resource is outside authorized scope",
    };
  }

  return { allowed: true };
}

export function actorHasRole(actor: ActorContext, role: Role): boolean {
  return actor.roles.includes(role);
}

export function canPerform(
  actor: ActorContext,
  resource: Resource,
  action: Action,
): boolean {
  return actor.assignments.some((assignment) =>
    hasScopedCapability(assignment.role, resource, action),
  );
}
