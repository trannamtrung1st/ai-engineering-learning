import type { FastifyPluginAsync } from "fastify";
import { assertEventScope } from "../../auth/scope.js";
import { getActor, requireRole } from "../../auth/middleware.js";
import { ensureAuditSchema } from "./repository.js";
import { auditService } from "./service.js";
import type { ListAuditLogsQuery, ListStatusHistoryQuery } from "./types.js";

interface EventParams {
  eventId: string;
}

export const auditRoutes: FastifyPluginAsync = async (app) => {
  await ensureAuditSchema();

  app.register(async (staffApp) => {
    staffApp.addHook(
      "onRequest",
      requireRole("OrganizerAdmin", "OrganizerStaff"),
    );

    staffApp.get<{
      Params: EventParams;
      Querystring: ListStatusHistoryQuery;
    }>("/events/:eventId/status-history", async (request) => {
      const actor = getActor(request);
      const { eventId } = request.params;
      assertEventScope(actor, eventId);

      return auditService.listStatusHistory(eventId, request.query);
    });
  });

  app.register(async (adminApp) => {
    adminApp.addHook("onRequest", requireRole("OrganizerAdmin"));

    adminApp.get<{ Params: EventParams; Querystring: ListAuditLogsQuery }>(
      "/events/:eventId/audit-logs",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);

        return auditService.listAuditLogs(eventId, request.query);
      },
    );
  });
};
