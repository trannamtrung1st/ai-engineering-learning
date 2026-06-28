import type { FastifyInstance } from "fastify";
import { Permission } from "../auth/permissions.js";
import {
  createAuthMiddleware,
  requirePermission,
} from "../auth/middleware.js";
import type { SessionStore } from "../auth/session-store.js";
import { reportAccessDenied } from "../errors/api-error.js";

/** Stub handlers for foundation RBAC and auth gate tests (NFR-10, NFR-11). */
export async function registerFoundationRoutes(
  app: FastifyInstance,
  store: SessionStore,
): Promise<void> {
  const auth = createAuthMiddleware(store);

  app.post(
    "/check-in",
    { preHandler: [auth, requirePermission(Permission.CheckinSubmit)] },
    async (request, reply) => {
      return reply.send({
        outcome: "Success",
        message: "Điểm danh thành công",
        requestId: request.requestId,
      });
    },
  );

  app.get(
    "/reports/summary",
    { preHandler: [auth, requirePermission(Permission.ReportRead, { reportAccess: true })] },
    async (request) => {
      const query = request.query as { classCode?: string };
      if (query.classCode === "HESD-02") {
        throw reportAccessDenied();
      }
      return { items: [], totalCount: 0 };
    },
  );

  app.post(
    "/reports/export",
    { preHandler: [auth, requirePermission(Permission.ReportExport, { exportAccess: true })] },
    async (_request, reply) => {
      return reply.type("text/csv").send("institutional_id,display_name\n");
    },
  );

  app.get(
    "/attendance/:recordId",
    { preHandler: [auth, requirePermission(Permission.AttendanceRead)] },
    async (request) => {
      const { user } = request.auth!;
      return { recordId: request.params, ownerId: user.id };
    },
  );

  app.get(
    "/attendance/me/history",
    { preHandler: [auth, requirePermission(Permission.AttendanceRead)] },
    async (request) => {
      const { user } = request.auth!;
      return { items: [{ ownerId: user.id }] };
    },
  );

  app.get(
    "/audit/logs",
    { preHandler: [auth, requirePermission(Permission.AuditRead)] },
    async () => ({ items: [] }),
  );
}
