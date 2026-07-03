import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { ErrorCode } from "@attendly/domain";
import { buildPaginationMeta } from "../academic-structure/pagination.js";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "../identity/middleware.js";
import { authDenied, resolveRequestId, sendApiError } from "../identity/http.js";
import type { AuditRepository } from "./repository.js";
import { resolveAuditReadScope } from "./scope.js";
import { parseAuditLogQuery } from "./validation.js";

function paginatedSuccess<T>(
  reply: FastifyReply,
  request: FastifyRequest,
  items: T[],
  page: number,
  pageSize: number,
  totalItems: number,
): void {
  void reply.status(200).send({
    data: items,
    meta: {
      requestId: resolveRequestId(request),
      timestamp: new Date().toISOString(),
      pagination: buildPaginationMeta(page, pageSize, totalItems),
    },
    error: null,
  });
}

export async function registerAuditRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: AuditRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);
  const guardAuditRead = createAuthorizeGuard(services, {
    resource: "AuditLog",
    action: "read",
    resolveScope: async (request) => {
      const actor = request.actor;
      if (!actor) return {};

      const institutionAssignment = actor.assignments.find(
        (assignment) => assignment.scopeType === "Institution",
      );
      if (institutionAssignment) {
        return {};
      }

      const facultyAssignment = actor.assignments.find(
        (assignment) => assignment.scopeType === "Faculty" && assignment.scopeId,
      );
      if (facultyAssignment?.scopeId) {
        return { facultyId: facultyAssignment.scopeId };
      }

      const sectionAssignment = actor.assignments.find(
        (assignment) => assignment.scopeType === "ClassSection" && assignment.scopeId,
      );
      if (sectionAssignment?.scopeId) {
        return { classSectionId: sectionAssignment.scopeId };
      }

      return {};
    },
  });

  app.get(
    "/audit-logs",
    { preHandler: combineGuards(authenticate, guardAuditRead) },
    async (request, reply) => {
      const parsed = parseAuditLogQuery(request.query as Record<string, unknown>);
      if (!parsed.ok) {
        sendApiError(
          reply,
          request,
          400,
          parsed.code === "InvalidFilter" ? ErrorCode.InvalidFilter : ErrorCode.InvalidPayload,
        );
        return;
      }

      const actor = request.actor;
      if (!actor) {
        sendApiError(reply, request, 401, ErrorCode.Unauthenticated);
        return;
      }

      const access = await resolveAuditReadScope(actor, services.repository, {
        classSectionId: parsed.filters.classSectionId,
        classSessionId: parsed.filters.classSessionId,
      });
      if (!access.allowed) {
        authDenied(reply, request, access.code);
        return;
      }

      const result = await repository.queryAuditLogs(parsed.filters, access.scope);
      paginatedSuccess(
        reply,
        request,
        result.items,
        parsed.filters.page,
        parsed.filters.pageSize,
        result.totalItems,
      );
    },
  );
}
