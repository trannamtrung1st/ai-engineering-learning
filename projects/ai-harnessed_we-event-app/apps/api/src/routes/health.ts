import type { FastifyPluginAsync } from "fastify";
import { checkDbHealth } from "../db/pool.js";

export const healthRoutes: FastifyPluginAsync = async (app) => {
  app.get("/health", async (request) => {
    const dbOk = await checkDbHealth();
    return {
      status: dbOk ? "ok" : "degraded",
      db: dbOk ? "connected" : "unavailable",
      requestId: request.id,
    };
  });
};
