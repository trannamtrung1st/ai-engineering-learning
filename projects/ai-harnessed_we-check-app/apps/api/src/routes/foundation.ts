import type { FastifyInstance } from "fastify";
import { Permission } from "../auth/permissions.js";
import {
  createAuthMiddleware,
  requirePermission,
} from "../auth/middleware.js";
import type { SessionStore } from "../auth/session-store.js";

/** Stub handlers for foundation RBAC and auth gate tests (NFR-10, NFR-11). */
export async function registerFoundationRoutes(
  app: FastifyInstance,
  store: SessionStore,
): Promise<void> {
  const auth = createAuthMiddleware(store);

  app.get(
    "/attendance/:recordId",
    { preHandler: [auth, requirePermission(Permission.AttendanceRead)] },
    async (request) => {
      const { user } = request.auth!;
      return { recordId: request.params, ownerId: user.id };
    },
  );

  app.get(
    "/audit/logs",
    { preHandler: [auth, requirePermission(Permission.AuditRead)] },
    async () => ({ items: [] }),
  );
}
