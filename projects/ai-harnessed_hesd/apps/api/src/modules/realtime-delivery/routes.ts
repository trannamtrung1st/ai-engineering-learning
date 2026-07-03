import type { FastifyInstance, FastifyRequest } from "fastify";
import { randomUUID } from "node:crypto";
import { ErrorCode } from "@attendly/domain";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "../identity/middleware.js";
import { sendApiError } from "../identity/http.js";
import { formatServerSentEvent, realtimeDeliveryGateway } from "./event-gateway.js";
import type { RealtimeDeliveryRepository } from "./repository.js";
import type { RealtimeRosterEvent } from "./types.js";

function paramsSessionId(request: FastifyRequest) {
  const params = request.params as { sessionId?: string };
  return { classSessionId: params.sessionId };
}

export async function registerRealtimeDeliveryRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: RealtimeDeliveryRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);
  const guardAttendanceRead = createAuthorizeGuard(services, {
    resource: "AttendanceRecord",
    action: "read",
    resolveScope: paramsSessionId,
  });

  app.get(
    "/class-sessions/:sessionId/attendance/events",
    { preHandler: combineGuards(authenticate, guardAttendanceRead) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      const roster = await repository.getRosterSnapshot(params.sessionId);
      if (!roster) {
        sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
        return;
      }

      reply.hijack();
      reply.raw.writeHead(200, {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      });

      const initial: RealtimeRosterEvent = {
        eventId: randomUUID(),
        type: "RosterUpdated",
        classSessionId: params.sessionId,
        reason: roster.state === "Open" ? "SessionOpened" : "SessionClosed",
        correlationId: request.requestId ?? null,
        roster,
        occurredAt: new Date().toISOString(),
      };
      reply.raw.write(formatServerSentEvent("roster.snapshot", initial));

      const unsubscribe = realtimeDeliveryGateway.subscribeToRoster(params.sessionId, (event) => {
        reply.raw.write(formatServerSentEvent("roster.update", event));
      });

      request.raw.on("close", unsubscribe);
    },
  );
}
