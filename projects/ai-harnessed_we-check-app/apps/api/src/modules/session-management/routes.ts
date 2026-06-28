import type { FastifyInstance } from "fastify";
import { ErrorCode } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import {
  createAuthMiddleware,
  requirePermission,
} from "../../auth/middleware.js";
import { Permission } from "../../auth/permissions.js";
import type { SessionStore } from "../../auth/session-store.js";
import { validationFailed } from "../../errors/api-error.js";
import { AutoCloseScheduler } from "./auto-close-scheduler.js";
import { SessionService } from "./session-service.js";
import type { NotificationService } from "../notifications/notification-service.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function registerSessionManagementRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
  notifications?: NotificationService,
): Promise<AutoCloseScheduler> {
  const sessionService = new SessionService(db, notifications);
  const autoClose = new AutoCloseScheduler(db, sessionService);
  const auth = createAuthMiddleware(store);

  app.get(
    "/sessions/:sessionId",
    { preHandler: [auth, requirePermission(Permission.SessionRead)] },
    async (request) => {
      const { sessionId } = request.params as { sessionId: string };
      if (!UUID_RE.test(sessionId)) {
        throw validationFailed([
          {
            field: "sessionId",
            code: ErrorCode.InvalidFormat,
            message: "Định dạng trường không hợp lệ",
          },
        ]);
      }
      const { user } = request.auth!;
      return sessionService.getById(sessionId, user.id, user.role);
    },
  );

  app.post(
    "/sessions",
    { preHandler: [auth, requirePermission(Permission.SessionWrite)] },
    async (request, reply) => {
      const { user } = request.auth!;
      const body = request.body as Parameters<SessionService["create"]>[0];
      const session = await sessionService.create(body, user.id, user.role);
      return reply.status(201).send(session);
    },
  );

  app.patch(
    "/sessions/:sessionId",
    { preHandler: [auth, requirePermission(Permission.SessionWrite)] },
    async (request) => {
      const { sessionId } = request.params as { sessionId: string };
      const { user } = request.auth!;
      const body = request.body as Parameters<SessionService["patch"]>[1];
      return sessionService.patch(sessionId, body, user.id, user.role);
    },
  );

  app.post(
    "/sessions/:sessionId/open",
    { preHandler: [auth, requirePermission(Permission.SessionWrite)] },
    async (request) => {
      const { sessionId } = request.params as { sessionId: string };
      const { user } = request.auth!;
      return sessionService.open(sessionId, user.id, user.role);
    },
  );

  app.post(
    "/sessions/:sessionId/close",
    { preHandler: [auth, requirePermission(Permission.SessionWrite)] },
    async (request) => {
      const { sessionId } = request.params as { sessionId: string };
      const { user } = request.auth!;
      return sessionService.close(sessionId, user.id, user.role);
    },
  );

  app.post(
    "/sessions/:sessionId/cancel",
    { preHandler: [auth, requirePermission(Permission.SessionWrite)] },
    async (request) => {
      const { sessionId } = request.params as { sessionId: string };
      const { user } = request.auth!;
      return sessionService.cancel(sessionId, user.id, user.role);
    },
  );

  app.get(
    "/sessions/:sessionId/attendance",
    { preHandler: [auth, requirePermission(Permission.AttendanceRead)] },
    async (request) => {
      const { sessionId } = request.params as { sessionId: string };
      const { user } = request.auth!;
      return sessionService.getAttendance(sessionId, user.id, user.role);
    },
  );

  app.get(
    "/sessions/:sessionId/qr/current",
    { preHandler: [auth, requirePermission(Permission.QrDisplay)] },
    async (request) => {
      const { sessionId } = request.params as { sessionId: string };
      const { user } = request.auth!;
      return sessionService.getCurrentQr(sessionId, user.id, user.role);
    },
  );

  return autoClose;
}
