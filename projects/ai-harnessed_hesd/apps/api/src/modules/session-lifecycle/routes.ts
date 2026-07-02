import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { ErrorCode } from "@attendly/domain";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "../identity/middleware.js";
import { resolveRequestId, sendApiError, sendApiSuccess } from "../identity/http.js";
import type { ApiErrorEnvelope } from "@attendly/domain";
import type { SessionLifecycleRepository } from "./repository.js";

const INVALID_TRANSITION_MESSAGE =
  "Không thể thực hiện thao tác cho trạng thái hiện tại.";

function paramsSessionId(request: FastifyRequest) {
  const params = request.params as { sessionId?: string };
  return { classSessionId: params.sessionId };
}

function idempotencyKey(request: FastifyRequest): string | undefined {
  const header = request.headers["idempotency-key"];
  return typeof header === "string" && header.length > 0 ? header : undefined;
}

function sendInvalidTransition(
  reply: FastifyReply,
  request: FastifyRequest,
  fromState: string,
): void {
  const body: ApiErrorEnvelope = {
    data: null,
    meta: {
      requestId: resolveRequestId(request),
      timestamp: new Date().toISOString(),
    },
    error: {
      code: ErrorCode.InvalidSessionTransition,
      message: INVALID_TRANSITION_MESSAGE,
      details: { fromState },
    },
  };
  void reply.status(409).send(body);
}

export async function registerSessionLifecycleRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: SessionLifecycleRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  const guardSessionControl = createAuthorizeGuard(services, {
    resource: "SessionControl",
    action: "execute",
    resolveScope: paramsSessionId,
  });

  app.post(
    "/class-sessions/:sessionId/open",
    { preHandler: combineGuards(authenticate, guardSessionControl) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      const body = (request.body ?? {}) as { roomId?: string };
      const actor = request.actor!;

      const outcome = await repository.openSession(params.sessionId, actor.userId, {
        roomId: body.roomId,
        idempotencyKey: idempotencyKey(request),
      });

      if (!outcome.ok) {
        if (outcome.error.code === "SessionNotFound") {
          sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
          return;
        }
        if (outcome.error.code === "InvalidSessionTransition") {
          sendInvalidTransition(reply, request, outcome.error.fromState);
          return;
        }
        sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
        return;
      }

      sendApiSuccess(reply, request, 200, outcome.result);
    },
  );

  app.post(
    "/class-sessions/:sessionId/close",
    { preHandler: combineGuards(authenticate, guardSessionControl) },
    async (request, reply) => {
      const params = request.params as { sessionId: string };
      const actor = request.actor!;

      const outcome = await repository.closeSession(params.sessionId, actor.userId, {
        idempotencyKey: idempotencyKey(request),
      });

      if (!outcome.ok) {
        if (outcome.error.code === "SessionNotFound") {
          sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
          return;
        }
        if (outcome.error.code === "InvalidSessionTransition") {
          sendInvalidTransition(reply, request, outcome.error.fromState);
          return;
        }
        sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
        return;
      }

      sendApiSuccess(reply, request, 200, outcome.result);
    },
  );
}
