import type { FastifyInstance } from "fastify";
import multipart from "@fastify/multipart";
import { ErrorCode, UserRole } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import {
  createAuthMiddleware,
  requirePermission,
} from "../../auth/middleware.js";
import { Permission } from "../../auth/permissions.js";
import type { SessionStore } from "../../auth/session-store.js";
import {
  forbidden,
  invalidFile,
  notFound,
  validationFailed,
} from "../../errors/api-error.js";
import { registerClassSubjectWriteRoutes } from "./class-subject-write/index.js";
import { validateCsvFile } from "./csv-validator.js";
import { RosterService } from "./roster-service.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function validateUuid(value: unknown, field: string): string | null {
  if (typeof value !== "string" || !UUID_RE.test(value)) {
    return field;
  }
  return null;
}

export async function registerRosterEnrollmentRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
): Promise<void> {
  await app.register(multipart, {
    limits: { fileSize: 5 * 1024 * 1024, files: 1 },
  });

  const rosterService = new RosterService(db);
  const auth = createAuthMiddleware(store);

  await registerClassSubjectWriteRoutes(app, db, store);

  app.get(
    "/classes",
    { preHandler: [auth, requirePermission(Permission.RosterRead)] },
    async (request) => {
      const { user } = request.auth!;
      const items = await rosterService.listClasses(user.id, user.role);
      return { items, totalCount: items.length };
    },
  );

  app.get(
    "/subjects",
    { preHandler: [auth, requirePermission(Permission.RosterRead)] },
    async (request) => {
      const { user } = request.auth!;
      const items = await rosterService.listSubjects(user.id, user.role);
      return { items, totalCount: items.length };
    },
  );

  app.get(
    "/enrollments",
    { preHandler: [auth, requirePermission(Permission.RosterRead)] },
    async (request) => {
      const query = request.query as Record<string, unknown>;
      const invalidFields = [
        validateUuid(query.classId, "classId"),
        validateUuid(query.subjectId, "subjectId"),
      ].filter((field): field is string => field !== null);

      if (invalidFields.length > 0) {
        throw validationFailed(
          invalidFields.map((field) => ({
            field,
            code: ErrorCode.InvalidFormat,
            message: "Định dạng trường không hợp lệ",
          })),
        );
      }

      const { user } = request.auth!;
      const result = await rosterService.getEnrollments(
        query.classId as string,
        query.subjectId as string,
        user.id,
        user.role,
      );

      return {
        class: result.class,
        subject: result.subject,
        enrollments: result.enrollments.map((entry) => ({
          enrollmentId: entry.enrollmentId,
          student: {
            id: entry.studentId,
            institutionalId: entry.institutionalId,
            displayName: entry.displayName,
          },
          enrolledAt: entry.enrolledAt.toISOString(),
        })),
        totalCount: result.totalCount,
      };
    },
  );

  app.post(
    "/roster/import",
    { preHandler: [auth, requirePermission(Permission.RosterWrite)] },
    async (request, reply) => {
      if (request.auth?.user.role !== UserRole.TrainingOfficeAdmin) {
        throw forbidden();
      }

      const parts = request.parts();
      let fileBuffer: Buffer | undefined;
      let fileName = "upload.csv";
      let mimeType: string | undefined;
      let dryRun = false;

      for await (const part of parts) {
        if (part.type === "file" && part.fieldname === "file") {
          fileBuffer = await part.toBuffer();
          fileName = part.filename || fileName;
          mimeType = part.mimetype;
        } else if (part.type === "field" && part.fieldname === "dryRun") {
          const value = String(part.value).toLowerCase();
          dryRun = value === "true" || value === "1";
        }
      }

      const fileCheck = validateCsvFile(fileBuffer, mimeType);
      if (!fileCheck.ok) {
        throw invalidFile();
      }

      const { user } = request.auth!;
      const started = await rosterService.startImport(fileCheck.buffer, {
        uploadedById: user.id,
        fileName,
        dryRun,
      });

      return reply.status(202).send({
        batchId: started.batchId,
        status: started.status,
        message: "Đang xử lý file danh sách...",
      });
    },
  );

  app.get(
    "/roster/imports/:batchId",
    { preHandler: [auth, requirePermission(Permission.RosterWrite)] },
    async (request) => {
      const { batchId } = request.params as { batchId: string };
      if (!UUID_RE.test(batchId)) {
        throw validationFailed([
          {
            field: "batchId",
            code: ErrorCode.InvalidFormat,
            message: "Định dạng trường không hợp lệ",
          },
        ]);
      }

      const batch = await rosterService.getImportBatch(batchId);
      if (!batch) {
        throw notFound();
      }

      return {
        batchId: batch.batchId,
        status: batch.status,
        totalRows: batch.totalRows,
        successRows: batch.successRows,
        errorRows: batch.errorRows,
        errorDetails: batch.errorDetails,
      };
    },
  );
}
