import { authorize } from "../identity/authorize.js";
import { capabilityForRole } from "../identity/permissions.js";
import type { IdentityRepository } from "../identity/repository.js";
import type { ActorContext, AuthDecision } from "../identity/types.js";
import type { AttendanceReportFilters, ResolvedReportScope } from "./types.js";

export type ScopeAccessResult =
  | { allowed: true; scope: ResolvedReportScope }
  | { allowed: false; code: "Forbidden" | "OutOfScope" };

function isStudentOnlyActor(actor: ActorContext): boolean {
  return actor.roles.length === 1 && actor.roles[0] === "Student";
}

function actorDeniedForResource(actor: ActorContext, resource: "ReportView" | "ExportJob"): boolean {
  const action = resource === "ReportView" ? "read" : "execute";
  const capable = actor.assignments.some((assignment) => {
    const effect = capabilityForRole(assignment.role, resource, action);
    return effect === "allow" || effect === "scoped";
  });
  if (!capable) return true;

  const onlyStudent =
    actor.assignments.every((assignment) => {
      const effect = capabilityForRole(assignment.role, resource, action);
      if (effect === "deny") return true;
      return assignment.role === "Student";
    }) &&
    actor.assignments.some((assignment) => {
      const effect = capabilityForRole(assignment.role, resource, action);
      return effect !== "deny";
    });

  return onlyStudent;
}

async function resolveStudentReportScope(
  actor: ActorContext,
  repository: IdentityRepository,
  filters: AttendanceReportFilters,
): Promise<ScopeAccessResult> {
  if (filters.studentUserId && filters.studentUserId !== actor.userId) {
    return { allowed: false, code: "Forbidden" };
  }

  const enrolledSections = await repository.getStudentEnrolledSectionIds(actor.userId);

  if (filters.classSectionId) {
    if (!enrolledSections.includes(filters.classSectionId)) {
      return { allowed: false, code: "OutOfScope" };
    }
    return {
      allowed: true,
      scope: {
        classSectionIds: [filters.classSectionId],
        studentUserId: actor.userId,
      },
    };
  }

  return {
    allowed: true,
    scope: {
      classSectionIds: enrolledSections,
      studentUserId: actor.userId,
    },
  };
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

export async function resolveReportExportScope(
  actor: ActorContext,
  repository: IdentityRepository,
  filters: AttendanceReportFilters,
  resource: "ReportView" | "ExportJob",
): Promise<ScopeAccessResult> {
  if (resource === "ReportView" && isStudentOnlyActor(actor)) {
    return resolveStudentReportScope(actor, repository, filters);
  }

  if (actorDeniedForResource(actor, resource)) {
    return { allowed: false, code: "Forbidden" };
  }

  if (filters.classSectionId) {
    const bindings = await repository.resolveScopeBindings({
      classSectionId: filters.classSectionId,
    });
    const lecturerSections = await repository.getLecturerClassSectionIds(actor.userId);
    const decision: AuthDecision = authorize(
      actor,
      resource,
      resource === "ReportView" ? "read" : "execute",
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
      scope: { classSectionIds: [filters.classSectionId] },
    };
  }

  const allowedSectionIds = await collectScopedSectionIds(actor, repository);

  if (allowedSectionIds !== null && allowedSectionIds.length === 0) {
    return { allowed: false, code: "OutOfScope" };
  }

  return {
    allowed: true,
    scope: { classSectionIds: allowedSectionIds },
  };
}
