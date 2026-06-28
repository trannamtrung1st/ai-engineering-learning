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
    "/users",
    { preHandler: [auth, requirePermission(Permission.UserWrite)] },
    async () => ({ items: [] }),
  );

  app.post(
    "/users",
    { preHandler: [auth, requirePermission(Permission.UserWrite)] },
    async (_request, reply) => reply.status(201).send({ id: "stub" }),
  );

  app.post(
    "/roster/import",
    { preHandler: [auth, requirePermission(Permission.RosterWrite)] },
    async (_request, reply) => reply.status(202).send({ status: "Processing" }),
  );

  app.post(
    "/sessions/:sessionId/open",
    { preHandler: [auth, requirePermission(Permission.SessionWrite)] },
    async () => ({ status: "Active" }),
  );

  app.post(
    "/sessions",
    { preHandler: [auth, requirePermission(Permission.SessionWrite)] },
    async (_request, reply) => reply.status(201).send({ status: "Draft" }),
  );

  app.get(
    "/sessions/:sessionId/qr/current",
    { preHandler: [auth, requirePermission(Permission.QrDisplay)] },
    async () => ({ qrPayload: "stub" }),
  );

  app.get(
    "/auth/me",
    { preHandler: [auth, requirePermission(Permission.UserRead)] },
    async (request) => {
      const { user } = request.auth!;
      return {
        id: user.id,
        institutionalId: user.institutionalId,
        displayName: user.displayName,
        email: user.email,
        role: user.role,
      };
    },
  );

  app.get(
    "/enrollments",
    { preHandler: [auth, requirePermission(Permission.RosterRead, { reportAccess: true })] },
    async (request) => {
      const query = request.query as { classId?: string };
      if (query.classId === "HESD-02") {
        throw reportAccessDenied();
      }
      return { items: [] };
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
