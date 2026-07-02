import type { FastifyInstance, FastifyRequest } from "fastify";
import { sendApiSuccess } from "./http.js";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "./middleware.js";

function queryClassSectionId(request: FastifyRequest) {
  const query = request.query as { classSectionId?: string };
  return { classSectionId: query.classSectionId };
}

function paramsSessionId(request: FastifyRequest) {
  const params = request.params as { sessionId?: string };
  return { classSessionId: params.sessionId };
}

function exportFilters(request: FastifyRequest) {
  const body = request.body as { filters?: { classSectionId?: string; termId?: string } };
  return { classSectionId: body?.filters?.classSectionId };
}

/** Auth-guarded route stubs — business handlers ship in downstream modules. */
export async function registerProtectedRouteStubs(
  app: FastifyInstance,
  services: IdentityServices,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  const guardReportRead = createAuthorizeGuard(services, {
    resource: "ReportView",
    action: "read",
    resolveScope: queryClassSectionId,
  });

  const guardExport = createAuthorizeGuard(services, {
    resource: "ExportJob",
    action: "execute",
    resolveScope: exportFilters,
  });

  const guardAuditRead = createAuthorizeGuard(services, {
    resource: "AuditLog",
    action: "read",
  });

  const guardAttendanceRead = createAuthorizeGuard(services, {
    resource: "AttendanceRecord",
    action: "read",
    resolveScope: paramsSessionId,
  });

  const guardAttendanceUpdate = createAuthorizeGuard(services, {
    resource: "AttendanceRecord",
    action: "update",
    resolveScope: paramsSessionId,
  });

  const guardSessionControl = createAuthorizeGuard(services, {
    resource: "SessionControl",
    action: "execute",
    resolveScope: paramsSessionId,
  });

  const guardCheckIn = createAuthorizeGuard(services, {
    resource: "CheckInSubmit",
    action: "execute",
  });

  const guardEnrollmentImport = createAuthorizeGuard(services, {
    resource: "Enrollment",
    action: "create",
    resolveScope: (request) => {
      const body = request.body as { classSectionId?: string };
      return { classSectionId: body.classSectionId };
    },
  });

  const emptyList = { items: [], pagination: { page: 1, pageSize: 25, totalItems: 0, totalPages: 0 } };

  app.get(
    "/reports/attendance",
    { preHandler: combineGuards(authenticate, guardReportRead) },
    async (request, reply) => {
      sendApiSuccess(reply, request, 200, emptyList);
    },
  );

  app.post(
    "/exports/attendance",
    { preHandler: combineGuards(authenticate, guardExport) },
    async (request, reply) => {
      sendApiSuccess(reply, request, 202, {
        exportJobId: "00000000-0000-4000-8000-000000000099",
        status: "Queued",
        format: "csv",
      });
    },
  );

  app.get(
    "/audit-logs",
    { preHandler: combineGuards(authenticate, guardAuditRead) },
    async (request, reply) => {
      sendApiSuccess(reply, request, 200, emptyList);
    },
  );

  app.get(
    "/class-sessions/:sessionId/attendance",
    { preHandler: combineGuards(authenticate, guardAttendanceRead) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      sendApiSuccess(reply, request, 200, {
        classSessionId: params.sessionId,
        state: "Open",
        counts: { present: 0, late: 0, pending: 0, rejectedAttempts: 0 },
        rows: [],
      });
    },
  );

  app.patch(
    "/class-sessions/:sessionId/attendance/:studentUserId",
    { preHandler: combineGuards(authenticate, guardAttendanceUpdate) },
    async (request, reply) => {
      sendApiSuccess(reply, request, 200, { status: "accepted" });
    },
  );

  app.post(
    "/class-sessions/:sessionId/open",
    { preHandler: combineGuards(authenticate, guardSessionControl) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      sendApiSuccess(reply, request, 200, { classSessionId: params.sessionId, state: "Open" });
    },
  );

  app.post(
    "/class-sessions/:sessionId/close",
    { preHandler: combineGuards(authenticate, guardSessionControl) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      sendApiSuccess(reply, request, 200, { classSessionId: params.sessionId, state: "Closed" });
    },
  );

  app.post(
    "/check-ins",
    { preHandler: combineGuards(authenticate, guardCheckIn) },
    async (request, reply) => {
      sendApiSuccess(reply, request, 501, { outcome: "NotImplemented" });
    },
  );

  app.post(
    "/enrollments/import",
    { preHandler: combineGuards(authenticate, guardEnrollmentImport) },
    async (request, reply) => {
      sendApiSuccess(reply, request, 200, { acceptedRows: 0, rejectedRows: [] });
    },
  );
}
