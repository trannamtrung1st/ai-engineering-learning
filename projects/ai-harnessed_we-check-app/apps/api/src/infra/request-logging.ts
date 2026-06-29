import type { FastifyInstance } from "fastify";

export interface RequestLogMeta {
  sessionId?: string;
  outcome?: string;
  errorCode?: string;
}

declare module "fastify" {
  interface FastifyRequest {
    requestLogMeta?: RequestLogMeta;
  }
}

/** Structured completion log per NFR-21 / error-handling §6.1 — never includes raw GPS or secrets. */
export function registerRequestLoggingHook(app: FastifyInstance): void {
  app.addHook("onResponse", async (request, reply) => {
    const entry: Record<string, unknown> = {
      requestId: request.requestId,
      method: request.method,
      path: request.url,
      status: reply.statusCode,
      durationMs: Math.round(reply.elapsedTime),
    };

    const userId = request.auth?.user.id;
    if (userId) {
      entry.userId = userId;
    }

    const meta = request.requestLogMeta;
    if (meta?.sessionId) {
      entry.sessionId = meta.sessionId;
    }
    if (meta?.outcome) {
      entry.outcome = meta.outcome;
    }
    if (meta?.errorCode) {
      entry.errorCode = meta.errorCode;
    }

    request.log.info(entry, "request completed");
  });
}
