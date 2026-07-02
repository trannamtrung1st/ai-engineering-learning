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

}
