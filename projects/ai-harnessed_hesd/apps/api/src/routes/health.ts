import type { FastifyInstance } from "fastify";
import type { HealthPayload } from "@attendly/domain";

export interface DbHealthProbe {
  ping(): Promise<boolean>;
}

const noopDbProbe: DbHealthProbe = {
  async ping() {
    return true;
  },
};

export function registerHealthRoutes(
  app: FastifyInstance,
  dbProbe: DbHealthProbe = noopDbProbe,
): void {
  app.get("/health", async (_request, reply) => {
    const dbConnected = await dbProbe.ping();
    const payload: HealthPayload = {
      status: dbConnected ? "ok" : "degraded",
      db: dbConnected ? "connected" : "disconnected",
    };

    if (!dbConnected) {
      return reply.status(503).send(payload);
    }

    return payload;
  });
}
