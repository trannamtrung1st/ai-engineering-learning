import type { FastifyInstance } from "fastify";
import { ErrorCode } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import {
  createAuthMiddleware,
  requirePermission,
} from "../../auth/middleware.js";
import { Permission } from "../../auth/permissions.js";
import type { SessionStore } from "../../auth/session-store.js";
import {
  invalidPagination,
  validationFailed,
} from "../../errors/api-error.js";
import { AttendanceService } from "./attendance-service.js";
import { validateHistoryQuery, validateManualEditBody } from "./validation.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function registerAttendanceRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
): Promise<void> {
  const attendanceService = new AttendanceService(db);
  const auth = createAuthMiddleware(store);

  app.patch(
    "/attendance/:recordId",
    { preHandler: [auth, requirePermission(Permission.AttendanceWrite)] },
    async (request) => {
      const { recordId } = request.params as { recordId: string };
      if (!UUID_RE.test(recordId)) {
        throw validationFailed([
          {
            field: "recordId",
            code: ErrorCode.InvalidFormat,
            message: "Định dạng trường không hợp lệ",
          },
        ]);
      }

      const parsed = validateManualEditBody(request.body);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }

      const { user } = request.auth!;
      return attendanceService.manualEdit(
        recordId,
        parsed.value,
        user.id,
        user.role,
      );
    },
  );

  app.get(
    "/attendance/me/history",
    { preHandler: [auth, requirePermission(Permission.AttendanceRead)] },
    async (request) => {
      const parsed = validateHistoryQuery(
        request.query as Record<string, unknown>,
      );
      if (!parsed.ok) {
        const hasPaginationError = parsed.details.some(
          (d) => d.code === ErrorCode.InvalidPagination,
        );
        if (hasPaginationError) {
          throw invalidPagination();
        }
        throw validationFailed(parsed.details);
      }

      const { user } = request.auth!;
      return attendanceService.getStudentHistory(user.id, parsed.value);
    },
  );
}

export { AttendanceService };
