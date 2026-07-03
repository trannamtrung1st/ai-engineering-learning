import type { FastifyInstance, FastifyRequest } from "fastify";
import { ErrorCode } from "@attendly/domain";
import { authorize } from "../identity/authorize.js";
import {
  createAuthenticate,
  type IdentityServices,
} from "../identity/middleware.js";
import { capabilityForRole } from "../identity/permissions.js";
import { sendApiError, sendApiSuccess } from "../identity/http.js";
import type { NotificationRepository } from "./repository.js";

function parseAlertQuery(request: FastifyRequest): {
  classSectionId?: string;
  studentUserId?: string;
} {
  const query = request.query as Record<string, unknown>;
  return {
    classSectionId:
      typeof query.classSectionId === "string" && query.classSectionId.length > 0
        ? query.classSectionId
        : undefined,
    studentUserId:
      typeof query.studentUserId === "string" && query.studentUserId.length > 0
        ? query.studentUserId
        : undefined,
  };
}

export async function registerNotificationRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: NotificationRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  app.get(
    "/alerts/absence-threshold",
    { preHandler: authenticate },
    async (request, reply) => {
      const actor = request.actor!;
      const query = parseAlertQuery(request);

      const isStudentOnly = actor.assignments.every((assignment) => {
        const readReport = capabilityForRole(assignment.role, "ReportView", "read");
        const readAlert = capabilityForRole(assignment.role, "AbsenceAlert", "read");
        const effect = readAlert !== "deny" ? readAlert : readReport;
        if (effect === "deny") return true;
        return assignment.role === "Student";
      });

      if (isStudentOnly) {
        if (query.studentUserId && query.studentUserId !== actor.userId) {
          sendApiError(reply, request, 403, ErrorCode.Forbidden);
          return;
        }

        const rows = await repository.listAbsenceThresholdAlerts({
          classSectionId: query.classSectionId,
          studentUserId: actor.userId,
          allowedSectionIds: null,
          selfUserId: actor.userId,
        });
        sendApiSuccess(reply, request, 200, { rows });
        return;
      }

      const capable = actor.assignments.some((assignment) => {
        const effect = capabilityForRole(assignment.role, "AbsenceAlert", "read");
        return effect === "allow" || effect === "scoped";
      });

      if (!capable) {
        sendApiError(reply, request, 403, ErrorCode.Forbidden);
        return;
      }

      if (query.classSectionId) {
        const bindings = await services.repository.resolveScopeBindings({
          classSectionId: query.classSectionId,
        });
        const lecturerSections = await services.repository.getLecturerClassSectionIds(actor.userId);
        const decision = authorize(
          actor,
          "AbsenceAlert",
          "read",
          { classSectionId: query.classSectionId, studentUserId: query.studentUserId },
          {
            classSectionFacultyId: bindings.classSectionFacultyId,
            classSectionIdsForFaculty: bindings.classSectionIdsForFaculty,
            lecturerClassSectionIds: lecturerSections,
          },
        );

        if (!decision.allowed) {
          sendApiError(reply, request, 403, decision.code);
          return;
        }

        const rows = await repository.listAbsenceThresholdAlerts({
          classSectionId: query.classSectionId,
          studentUserId: query.studentUserId,
          allowedSectionIds: [query.classSectionId],
        });
        sendApiSuccess(reply, request, 200, { rows });
        return;
      }

      const allowedSectionIds: string[] | null = actor.assignments.some(
        (assignment) => assignment.role === "AcademicAdmin",
      )
        ? null
        : [];

      if (allowedSectionIds) {
        for (const assignment of actor.assignments) {
          if (
            assignment.role === "Lecturer" &&
            assignment.scopeType === "ClassSection" &&
            assignment.scopeId
          ) {
            allowedSectionIds.push(assignment.scopeId);
          }
          if (
            (assignment.role === "DepartmentAdmin" || assignment.role === "SystemAuditor") &&
            assignment.scopeType === "Faculty" &&
            assignment.scopeId
          ) {
            const bindings = await services.repository.resolveScopeBindings({
              facultyId: assignment.scopeId,
            });
            for (const sectionId of bindings.classSectionIdsForFaculty ?? []) {
              allowedSectionIds.push(sectionId);
            }
          }
        }
      }

      const rows = await repository.listAbsenceThresholdAlerts({
        studentUserId: query.studentUserId,
        allowedSectionIds,
      });
      sendApiSuccess(reply, request, 200, { rows });
    },
  );
}
