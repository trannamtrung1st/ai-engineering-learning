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
import { NotificationService } from "./notification-service.js";
import {
  validateAbsenceThresholdBody,
  validateNotificationListQuery,
} from "./validation.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function registerNotificationRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
): Promise<NotificationService> {
  const notificationService = new NotificationService(db);
  const auth = createAuthMiddleware(store);

  app.get(
    "/notifications",
    { preHandler: [auth, requirePermission(Permission.NotificationRead)] },
    async (request) => {
      const parsed = validateNotificationListQuery(
        request.query as Record<string, unknown>,
      );
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }

      const { user } = request.auth!;
      return notificationService.listForUser(user.id, parsed.value);
    },
  );

  app.patch(
    "/notifications/:notificationId/read",
    { preHandler: [auth, requirePermission(Permission.NotificationRead)] },
    async (request, reply) => {
      const { notificationId } = request.params as { notificationId: string };
      if (!UUID_RE.test(notificationId)) {
        throw validationFailed([
          {
            field: "notificationId",
            code: ErrorCode.InvalidFormat,
            message: "Định dạng trường không hợp lệ",
          },
        ]);
      }

      const { user } = request.auth!;
      await notificationService.markRead(notificationId, user.id);
      return reply.status(204).send();
    },
  );

  app.get(
    "/policy/absence-threshold",
    { preHandler: [auth, requirePermission(Permission.PolicyWrite)] },
    async () => {
      const thresholdPercent =
        await notificationService.getAbsenceThresholdPercent();
      return { thresholdPercent };
    },
  );

  app.put(
    "/policy/absence-threshold",
    { preHandler: [auth, requirePermission(Permission.PolicyWrite)] },
    async (request) => {
      const parsed = validateAbsenceThresholdBody(request.body);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }

      const adminId = request.auth!.user.id;
      return notificationService.setAbsenceThresholdPercent(
        parsed.value.thresholdPercent,
        adminId,
      );
    },
  );

  return notificationService;
}
