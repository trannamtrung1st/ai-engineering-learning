import type { FastifyInstance, FastifyRequest } from "fastify";
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
import { UserRepository } from "./user-repository.js";
import { UserImportService } from "./user-import-service.js";
import { validateUserCsvFile } from "./user-import-csv.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function requireAdmin(request: FastifyRequest): void {
  if (request.auth?.user.role !== UserRole.TrainingOfficeAdmin) {
    throw forbidden();
  }
}

export async function registerUserImportRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
): Promise<void> {
  const users = new UserRepository(db);
  const userImportService = new UserImportService(db, users);
  const auth = createAuthMiddleware(store);

  app.post(
    "/users/import",
    { preHandler: [auth, requirePermission(Permission.UserWrite)] },
    async (request, reply) => {
      requireAdmin(request);

      const parts = request.parts();
      let fileBuffer: Buffer | undefined;
      let fileName = "users.csv";
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

      const fileCheck = validateUserCsvFile(fileBuffer, mimeType);
      if (!fileCheck.ok) {
        throw invalidFile();
      }

      const { user } = request.auth!;
      const started = await userImportService.startImport(fileCheck.buffer, {
        uploadedById: user.id,
        fileName,
        dryRun,
      });

      return reply.status(202).send({
        batchId: started.batchId,
        status: started.status,
        message: "Đang xử lý file người dùng...",
      });
    },
  );

  app.get(
    "/users/imports/:batchId",
    { preHandler: [auth, requirePermission(Permission.UserWrite)] },
    async (request) => {
      requireAdmin(request);
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

      const batch = await userImportService.getImportBatch(batchId);
      if (!batch) {
        throw notFound();
      }

      return {
        id: batch.batchId,
        batchId: batch.batchId,
        status: batch.status,
        totalRows: batch.totalRows,
        successRows: batch.successRows,
        errorRows: batch.errorRows,
        createdCount: batch.createdCount,
        updatedCount: batch.updatedCount,
        errorDetails: batch.errorDetails,
      };
    },
  );
}
