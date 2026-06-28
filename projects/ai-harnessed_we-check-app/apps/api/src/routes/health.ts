import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { checkDbConnection, type DbPool } from "../infra/db.js";

export async function registerHealthRoutes(
  app: FastifyInstance,
  db: DbPool,
): Promise<void> {
  app.get("/health", async (_request, reply) => {
    const connected = await checkDbConnection(db);
    if (!connected) {
      return reply.status(503).send({
        status: "degraded",
        db: "disconnected",
      });
    }
    return reply.send({ status: "ok", db: "connected" });
  });
}

export function registerRequestIdHook(app: FastifyInstance): void {
  app.addHook("onRequest", async (request, reply) => {
    const incoming = request.headers["x-request-id"];
    const requestId =
      typeof incoming === "string" && incoming.length > 0
        ? incoming
        : randomUUID();
    request.requestId = requestId;
    reply.header("X-Request-Id", requestId);
  });
}
