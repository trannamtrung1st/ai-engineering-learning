import type { FastifyInstance } from "fastify";
import { ErrorCode } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { createAuthMiddleware, requirePermission } from "../../auth/middleware.js";
import { Permission } from "../../auth/permissions.js";
import type { SessionStore } from "../../auth/session-store.js";
import { validationFailed } from "../../errors/api-error.js";
import { ExportService } from "./export-service.js";
import { exportFilename } from "./csv-formatter.js";
import { ReportService } from "./report-service.js";
import { validateReportFilter } from "./validation.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function registerReportingExportRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
): Promise<void> {
  const reportService = new ReportService(db);
  const exportService = new ExportService(db);
  const auth = createAuthMiddleware(store);

  app.get(
    "/reports/session/:sessionId",
    { preHandler: [auth, requirePermission(Permission.ReportRead, { reportAccess: true })] },
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
      return reportService.getSessionRoster(sessionId, user.id, user.role);
    },
  );

  app.get(
    "/reports/summary",
    { preHandler: [auth, requirePermission(Permission.ReportRead, { reportAccess: true })] },
    async (request) => {
      const parsed = validateReportFilter(request.query as Record<string, unknown>);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }

      const { user } = request.auth!;
      return reportService.getClassSubjectSummary(
        parsed.value,
        user.id,
        user.role,
      );
    },
  );

  app.get(
    "/reports/sessions",
    { preHandler: [auth, requirePermission(Permission.ReportRead, { reportAccess: true })] },
    async (request) => {
      const parsed = validateReportFilter(request.query as Record<string, unknown>);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }

      const { user } = request.auth!;
      return reportService.listSessionSummaries(
        parsed.value,
        user.id,
        user.role,
      );
    },
  );

  app.head(
    "/reports/export",
    { preHandler: [auth] },
    async (request, reply) => {
      const parsed = validateReportFilter(request.query as Record<string, unknown>, {
        requireClassSubject: true,
      });
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }

      const { user } = request.auth!;
      const rowCount = await exportService.estimateRowCount(
        parsed.value,
        user.id,
        user.role,
      );

      return reply
        .header("X-Export-Row-Count", String(rowCount))
        .status(200)
        .send();
    },
  );

  app.post(
    "/reports/export",
    // BR-09 / NFR-15: export RBAC + ExportDenied audit live in ExportService so denials
    // are always logged (permission guard would bypass security audit on HTTP path).
    { preHandler: [auth] },
    async (request, reply) => {
      const parsed = validateReportFilter(request.body as Record<string, unknown>, {
        requireClassSubject: true,
      });
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }

      const { user } = request.auth!;
      const result = await exportService.exportCsv(
        parsed.value,
        user.id,
        user.role,
      );

      const filename = exportFilename();
      return reply
        .type("text/csv; charset=utf-8")
        .header("Content-Disposition", `attachment; filename="${filename}"`)
        .send(result.csv);
    },
  );
}
