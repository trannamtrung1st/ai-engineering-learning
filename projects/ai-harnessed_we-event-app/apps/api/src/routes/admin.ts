import type { FastifyPluginAsync } from "fastify";
import { getActor, requireRole } from "../auth/middleware.js";

export const adminRoutes: FastifyPluginAsync = async (app) => {
  app.addHook("onRequest", requireRole("OrganizerAdmin"));

  app.get("/admin/status", async (request) => {
    const actor = getActor(request);
    return {
      status: "ok",
      actorId: actor.sub,
      role: actor.role,
    };
  });
};
