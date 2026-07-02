import { randomBytes, randomUUID } from "node:crypto";
import { ErrorCode, UserImportStatus } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { UserImportBatchRepository } from "./user-import-batch-repository.js";
import {
  mapUserCsvRows,
  normalizeUserEmail,
  parseUserActive,
  parseUserCsvContent,
  validateUserImportRow,
} from "./user-import-csv.js";
import { hashPassword } from "./password-hasher.js";
import { UserRepository } from "./user-repository.js";
import type { UserRecord } from "./types.js";
import type {
  UserImportCsvOptions,
  UserImportErrorDetail,
  UserImportSummary,
} from "./user-import-types.js";

function generateInitialPassword(): string {
  return randomBytes(16).toString("base64url").slice(0, 16);
}

function profileMatches(
  existing: UserRecord,
  row: {
    displayName: string;
    email: string;
    role: UserRecord["role"];
    active: boolean;
  },
): boolean {
  return (
    existing.displayName === row.displayName.trim() &&
    existing.email === normalizeUserEmail(row.email) &&
    existing.role === row.role &&
    existing.active === row.active
  );
}

export class UserImportService {
  private readonly batches: UserImportBatchRepository;

  constructor(
    private readonly db: DbPool,
    private readonly users: UserRepository,
  ) {
    this.batches = new UserImportBatchRepository(db);
  }

  async startImport(
    csvBuffer: Buffer,
    options: UserImportCsvOptions,
  ): Promise<{ batchId: string; status: typeof UserImportStatus.Processing }> {
    const batchId = await this.batches.createProcessing(
      options.uploadedById,
      options.fileName,
    );

    setImmediate(() => {
      void this.processImportBatch(
        batchId,
        csvBuffer,
        options.dryRun ?? false,
        true,
      ).catch(() => {
        /* logged at repository layer in production */
      });
    });

    return { batchId, status: UserImportStatus.Processing };
  }

  async importCsv(
    csvBuffer: Buffer,
    options: UserImportCsvOptions,
  ): Promise<UserImportSummary> {
    const dryRun = options.dryRun ?? false;
    const batchId = dryRun
      ? randomUUID()
      : await this.batches.createProcessing(
          options.uploadedById,
          options.fileName,
        );
    return this.processImportBatch(batchId, csvBuffer, dryRun, !dryRun);
  }

  async getImportBatch(batchId: string): Promise<UserImportSummary | null> {
    const batch = await this.batches.findById(batchId);
    if (!batch) {
      return null;
    }
    return {
      batchId: batch.batchId,
      status: batch.status,
      totalRows: batch.totalRows,
      successRows: batch.successRows,
      errorRows: batch.errorRows,
      createdCount: batch.createdCount,
      updatedCount: batch.updatedCount,
      errorDetails: batch.errorDetails,
    };
  }

  private async processImportBatch(
    batchId: string,
    csvBuffer: Buffer,
    dryRun: boolean,
    persistBatch: boolean,
  ): Promise<UserImportSummary> {
    const content = csvBuffer.toString("utf8");
    const { headers, rows } = parseUserCsvContent(content);
    const mapped = mapUserCsvRows(headers, rows);

    if (!mapped.ok) {
      const summary = {
        totalRows: rows.length,
        successRows: 0,
        errorRows: rows.length,
        createdCount: 0,
        updatedCount: 0,
        errorDetails: mapped.errors,
      };
      if (persistBatch) {
        await this.batches.complete(batchId, summary);
      }
      return { batchId, status: UserImportStatus.Completed, ...summary };
    }

    const errorDetails: UserImportErrorDetail[] = [];
    let successRows = 0;
    let createdCount = 0;
    let updatedCount = 0;

    const client = dryRun ? null : await this.db.connect();

    try {
      if (client) {
        await client.query("BEGIN");
      }

      for (const row of mapped.rows) {
        const fieldError = validateUserImportRow(row);
        if (fieldError) {
          errorDetails.push(fieldError);
          continue;
        }

        const institutionalId = row.institutionalId.trim();
        const displayName = row.displayName.trim();
        const email = normalizeUserEmail(row.email);
        const role = row.role;
        const active = parseUserActive(row.rawActive)!;

        const emailOwner = client
          ? await this.users.findByEmailOnClient(client, email)
          : await this.users.findByEmail(email);
        const existing = client
          ? await this.users.findByInstitutionalIdOnClient(client, institutionalId)
          : await this.users.findByInstitutionalId(institutionalId);

        if (
          emailOwner &&
          emailOwner.institutionalId !== institutionalId
        ) {
          errorDetails.push({
            rowNumber: row.rowNumber,
            field: "email",
            errorCode: ErrorCode.DuplicateEmail,
            message: "DuplicateEmail",
          });
          continue;
        }

        if (existing) {
          if (profileMatches(existing, { displayName, email, role, active })) {
            successRows += 1;
            continue;
          }

          if (!dryRun && client) {
            await this.users.updateOnClient(client, existing.id, {
              displayName,
              email,
              role,
              active,
            });
          }
          successRows += 1;
          updatedCount += 1;
          continue;
        }

        if (!dryRun && client) {
          const passwordHash = await hashPassword(generateInitialPassword());
          await this.users.createOnClient(client, {
            institutionalId,
            displayName,
            email,
            passwordHash,
            role,
            active,
          });
        }
        successRows += 1;
        createdCount += 1;
      }

      if (client) {
        await client.query("COMMIT");
      }
    } catch (error) {
      if (client) {
        await client.query("ROLLBACK");
      }
      throw error;
    } finally {
      client?.release();
    }

    const summary = {
      totalRows: mapped.rows.length,
      successRows,
      errorRows: errorDetails.length,
      createdCount,
      updatedCount,
      errorDetails,
    };

    if (persistBatch) {
      await this.batches.complete(batchId, summary);
    }

    return {
      batchId,
      status: UserImportStatus.Completed,
      ...summary,
    };
  }
}

export async function truncateUserImportTables(db: DbPool): Promise<void> {
  await db.query("TRUNCATE user_import_batches RESTART IDENTITY CASCADE");
}
