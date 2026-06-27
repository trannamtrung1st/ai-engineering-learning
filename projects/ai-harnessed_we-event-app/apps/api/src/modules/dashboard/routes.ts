import type { FastifyPluginAsync } from "fastify";
import { assertEventScope } from "../../auth/scope.js";
import { getActor, requireRole } from "../../auth/middleware.js";
import { ensureDashboardSchema } from "./repository.js";
import { dashboardService } from "./service.js";

interface EventParams {
  eventId: string;
}

export const dashboardRoutes: FastifyPluginAsync = async (app) => {
  await ensureDashboardSchema();

  app.register(async (adminApp) => {
    adminApp.addHook("onRequest", requireRole("OrganizerAdmin"));

    adminApp.get<{ Params: EventParams }>(
      "/events/:eventId/dashboard",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);

        return dashboardService.getEventDashboard(eventId);
      },
    );
  });
};
