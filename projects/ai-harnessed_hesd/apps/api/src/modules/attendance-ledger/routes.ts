import type { FastifyInstance, FastifyRequest } from "fastify";
import { ErrorCode } from "@attendly/domain";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "../identity/middleware.js";
import { sendApiError, sendApiSuccess } from "../identity/http.js";
import type { AttendanceLedgerRepository } from "./repository.js";

function paramsSessionId(request: FastifyRequest) {
  const params = request.params as { sessionId?: string };
  return { classSessionId: params.sessionId };
}

function idempotencyKey(request: FastifyRequest): string | undefined {
  const header = request.headers["idempotency-key"];
  return typeof header === "string" && header.length > 0 ? header : undefined;
}

export async function registerAttendanceLedgerRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: AttendanceLedgerRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  const guardAttendanceRead = createAuthorizeGuard(services, {
    resource: "AttendanceRecord",
    action: "read",
    resolveScope: paramsSessionId,
  });

  const guardAttendanceUpdate = createAuthorizeGuard(services, {
    resource: "AttendanceRecord",
    action: "update",
    resolveScope: paramsSessionId,
  });

  app.get(
    "/class-sessions/:sessionId/attendance",
    { preHandler: combineGuards(authenticate, guardAttendanceRead) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      const roster = await repository.getSessionRoster(params.sessionId);
      if (!roster) {
        sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
        return;
      }
      sendApiSuccess(reply, request, 200, roster);
    },
  );

  app.patch(
    "/class-sessions/:sessionId/attendance/:studentUserId",
    { preHandler: combineGuards(authenticate, guardAttendanceUpdate) },
    async (request, reply) => {
      const params = request.params as { sessionId: string; studentUserId: string };
      const actor = request.actor!;

      const outcome = await repository.correctAttendance({
        sessionId: params.sessionId,
        studentUserId: params.studentUserId,
        actor,
        body: (request.body ?? {}) as { status?: unknown; reason?: unknown },
        idempotencyKey: idempotencyKey(request),
        correlationId: request.requestId,
      });

      if (!outcome.ok) {
        if (outcome.error.code === "SessionNotFound") {
          sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
          return;
        }
        if (outcome.error.code === "NotEnrolled" || outcome.error.code === "StudentNotFound") {
          sendApiError(reply, request, 404, ErrorCode.StudentNotFound);
          return;
        }
        if (outcome.error.code === "ReasonRequired") {
          sendApiError(reply, request, 400, ErrorCode.ReasonRequired);
          return;
        }
        if (outcome.error.code === "EditWindowExpired") {
          sendApiError(reply, request, 409, ErrorCode.EditWindowExpired);
          return;
        }
        sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
        return;
      }

      sendApiSuccess(reply, request, 200, outcome.result);
    },
  );
}
