import type { FastifyPluginAsync } from "fastify";
import { getActor, requireCapability } from "../auth/middleware.js";

export const adminRoutes: FastifyPluginAsync = async (app) => {
  app.addHook("onRequest", requireCapability("audit.read"));

  app.get("/admin/status", async (request) => {
    const actor = getActor(request);
    return {
      status: "ok",
      actorId: actor.sub,
      role: actor.role,
    };
  });
};
