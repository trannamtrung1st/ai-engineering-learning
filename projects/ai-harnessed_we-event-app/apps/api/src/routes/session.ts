import type { FastifyPluginAsync } from "fastify";
import { getActor } from "../auth/middleware.js";

export const sessionRoutes: FastifyPluginAsync = async (app) => {
  app.get("/me", async (request) => {
    const actor = getActor(request);
    return {
      actorId: actor.sub,
      role: actor.role,
      assignedEventIds: actor.assignedEventIds ?? [],
    };
  });
};
