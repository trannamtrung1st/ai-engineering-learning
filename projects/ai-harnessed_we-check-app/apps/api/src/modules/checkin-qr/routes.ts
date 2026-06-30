import type { FastifyInstance } from "fastify";
import type { DbPool } from "../../infra/db.js";
import {
  createAuthMiddleware,
  requirePermission,
} from "../../auth/middleware.js";
import { Permission } from "../../auth/permissions.js";
import type { SessionStore } from "../../auth/session-store.js";
import { validationFailed } from "../../errors/api-error.js";
import type { CheckInFailureResponse, PreflightFailureResponse } from "./types.js";
import { CheckInService } from "./check-in-service.js";
import { checkInHttpStatus } from "./check-in-response.js";
import { PreflightService, preflightHttpStatus } from "./preflight/index.js";
import { validateCheckInBody } from "./validation.js";

export async function registerCheckInQrRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
): Promise<void> {
  const checkInService = new CheckInService(db);
  const preflightService = new PreflightService(db);
  const auth = createAuthMiddleware(store);

  app.get(
    "/check-in/tokens/:tokenId/preflight",
    { preHandler: [auth, requirePermission(Permission.CheckinSubmit)] },
    async (request, reply) => {
      const { tokenId } = request.params as { tokenId: string };
      const query = request.query as { sessionId?: string };
      const { user } = request.auth!;

      const result = await preflightService.validate(
        tokenId,
        user.id,
        query.sessionId ?? null,
      );

      if (result.outcome === "Valid") {
        return reply.status(200).send(result);
      }

      const failure = result as PreflightFailureResponse;
      return reply.status(preflightHttpStatus(failure.errorCode)).send(failure);
    },
  );

  app.post(
    "/check-in",
    { preHandler: [auth, requirePermission(Permission.CheckinSubmit)] },
    async (request, reply) => {
      const parsed = validateCheckInBody(request.body);
      if (!parsed.ok) {
        throw validationFailed(parsed.errors);
      }

      const { user } = request.auth!;
      const userAgent = request.headers["user-agent"] ?? null;
      const result = await checkInService.submit(
        parsed.value,
        user.id,
        userAgent,
      );

      const sessionId = await checkInService.sessionIdForToken(parsed.value.tokenId);
      request.requestLogMeta = {
        sessionId: sessionId ?? undefined,
        outcome: result.outcome,
        errorCode:
          result.outcome !== "Success"
            ? (result as CheckInFailureResponse).errorCode
            : undefined,
      };

      if (result.outcome === "Success") {
        return reply.status(200).send(result);
      }

      const failure = result as CheckInFailureResponse;
      return reply.status(checkInHttpStatus(failure.errorCode)).send(failure);
    },
  );
}
