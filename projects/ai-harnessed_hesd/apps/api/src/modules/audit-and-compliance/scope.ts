import { authorize } from "../identity/authorize.js";
import { capabilityForRole } from "../identity/permissions.js";
import type { IdentityRepository } from "../identity/repository.js";
import type { ActorContext } from "../identity/types.js";
import type { ResolvedAuditReadScope } from "./types.js";

const TECHNICAL_ACTION_TYPES = new Set([
  "SessionOpen",
  "SessionClose",
  "PolicyChange",
  "EnrollmentImport",
]);

export type AuditAccessResult =
  | { allowed: true; scope: ResolvedAuditReadScope }
  | { allowed: false; code: "Forbidden" | "OutOfScope" };

function actorDeniedAuditRead(actor: ActorContext): boolean {
  return !actor.assignments.some((assignment) => {
    const effect = capabilityForRole(assignment.role, "AuditLog", "read");
    return effect === "allow" || effect === "scoped";
  });
}

async function collectScopedSectionIds(
  actor: ActorContext,
  repository: IdentityRepository,
): Promise<string[] | null> {
  if (actor.assignments.some((a) => a.role === "AcademicAdmin")) {
    return null;
  }

  const sectionIds = new Set<string>();

  for (const assignment of actor.assignments) {
    if (assignment.role === "Lecturer" && assignment.scopeType === "ClassSection" && assignment.scopeId) {
      sectionIds.add(assignment.scopeId);
    }

    if (
      (assignment.role === "DepartmentAdmin" || assignment.role === "SystemAuditor") &&
      assignment.scopeType === "Faculty" &&
      assignment.scopeId
    ) {
      const bindings = await repository.resolveScopeBindings({ facultyId: assignment.scopeId });
      for (const id of bindings.classSectionIdsForFaculty ?? []) {
        sectionIds.add(id);
      }
    }
  }

  return [...sectionIds];
}

function isTechnicalOnlyActor(actor: ActorContext): boolean {
  const hasItAdmin = actor.assignments.some((a) => a.role === "ITAdmin");
  const hasAcademicRead = actor.assignments.some((a) => {
    const effect = capabilityForRole(a.role, "AuditLog", "read");
    return (
      effect !== "deny" &&
      (a.role === "AcademicAdmin" ||
        a.role === "Lecturer" ||
        a.role === "DepartmentAdmin" ||
        a.role === "SystemAuditor")
    );
  });
  return hasItAdmin && !hasAcademicRead;
}

export async function resolveAuditReadScope(
  actor: ActorContext,
  repository: IdentityRepository,
  filters: { classSectionId?: string; classSessionId?: string },
): Promise<AuditAccessResult> {
  if (actorDeniedAuditRead(actor)) {
    return { allowed: false, code: "Forbidden" };
  }

  const technicalOnly = isTechnicalOnlyActor(actor);

  if (filters.classSectionId) {
    const bindings = await repository.resolveScopeBindings({
      classSectionId: filters.classSectionId,
    });
    const lecturerSections = await repository.getLecturerClassSectionIds(actor.userId);
    const decision = authorize(
      actor,
      "AuditLog",
      "read",
      { classSectionId: filters.classSectionId },
      {
        classSectionFacultyId: bindings.classSectionFacultyId,
        classSectionIdsForFaculty: bindings.classSectionIdsForFaculty,
        lecturerClassSectionIds: lecturerSections,
      },
    );
    if (!decision.allowed) {
      return { allowed: false, code: decision.code };
    }
    return {
      allowed: true,
      scope: {
        institutionWide: false,
        classSectionIds: [filters.classSectionId],
        technicalOnly,
      },
    };
  }

  if (filters.classSessionId) {
    const bindings = await repository.resolveScopeBindings({
      classSessionId: filters.classSessionId,
    });
    const sectionId = bindings.sessionClassSectionId;
    if (!sectionId) {
      return { allowed: false, code: "OutOfScope" };
    }
    const lecturerSections = await repository.getLecturerClassSectionIds(actor.userId);
    const decision = authorize(
      actor,
      "AuditLog",
      "read",
      { classSectionId: sectionId, classSessionId: filters.classSessionId },
      {
        classSectionFacultyId: bindings.classSectionFacultyId,
        classSectionIdsForFaculty: bindings.classSectionIdsForFaculty,
        lecturerClassSectionIds: lecturerSections,
      },
    );
    if (!decision.allowed) {
      return { allowed: false, code: decision.code };
    }
    return {
      allowed: true,
      scope: {
        institutionWide: false,
        classSectionIds: [sectionId],
        technicalOnly,
      },
    };
  }

  const allowedSectionIds = await collectScopedSectionIds(actor, repository);
  if (allowedSectionIds !== null && allowedSectionIds.length === 0) {
    return { allowed: false, code: "OutOfScope" };
  }

  return {
    allowed: true,
    scope: {
      institutionWide: allowedSectionIds === null,
      classSectionIds: allowedSectionIds,
      technicalOnly,
    },
  };
}

export function isTechnicalAuditAction(dbActionType: string): boolean {
  return TECHNICAL_ACTION_TYPES.has(dbActionType);
}
