import type { FastifyPluginAsync } from "fastify";
import { assertEventScope } from "../../auth/scope.js";
import { getActor, requireRole } from "../../auth/middleware.js";
import { ensureAuditSchema } from "./repository.js";
import { auditService } from "./service.js";

interface EventParams {
  eventId: string;
}

interface AuditLogsQuery {
  entityType?: string;
  entityId?: string;
  limit?: string;
}

interface StatusHistoryQuery {
  registrationId?: string;
  limit?: string;
}

function parseLimit(value: string | undefined): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? undefined : parsed;
}

export const auditRoutes: FastifyPluginAsync = async (app) => {
  await ensureAuditSchema();

  app.register(async (staffApp) => {
    staffApp.addHook(
      "onRequest",
      requireRole("OrganizerAdmin", "OrganizerStaff"),
    );

    staffApp.get<{ Params: EventParams; Querystring: StatusHistoryQuery }>(
      "/events/:eventId/status-history",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);

        return auditService.listStatusHistory(eventId, {
          registrationId: request.query.registrationId,
          limit: parseLimit(request.query.limit),
        });
      },
    );
  });

  app.register(async (adminApp) => {
    adminApp.addHook("onRequest", requireRole("OrganizerAdmin"));

    adminApp.get<{ Params: EventParams; Querystring: AuditLogsQuery }>(
      "/events/:eventId/audit-logs",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);

        return auditService.listAuditLogs(eventId, {
          entityType: request.query.entityType,
          entityId: request.query.entityId,
          limit: parseLimit(request.query.limit),
        });
      },
    );
  });
};
