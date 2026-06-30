import { randomUUID } from "node:crypto";
import { RosterImportStatus, UserRole, type UserRole as UserRoleType } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { forbidden, notFound } from "../../errors/api-error.js";
import { UserRepository } from "../identity-auth/user-repository.js";
import { hashPassword } from "../identity-auth/password-hasher.js";
import { AssignmentRepository } from "./assignment-repository.js";
import {
  mapCsvRows,
  parseCsvContent,
  ROSTER_ROW_ERROR_MESSAGES,
  RosterRowErrorCode,
  validateRowFields,
} from "./csv-validator.js";
import { EnrollmentRepository } from "./enrollment-repository.js";
import { ImportBatchRepository } from "./import-batch-repository.js";
import { ReferenceRepository } from "./reference-repository.js";
import type {
  ClassRecord,
  EnrollmentRecord,
  ImportCsvOptions,
  ImportErrorDetail,
  ImportSummary,
  SubjectRecord,
} from "./types.js";

export class RosterService {
  private readonly references: ReferenceRepository;
  private readonly enrollments: EnrollmentRepository;
  private readonly assignments: AssignmentRepository;
  private readonly batches: ImportBatchRepository;
  private readonly users: UserRepository;

  constructor(private readonly db: DbPool) {
    this.references = new ReferenceRepository(db);
    this.enrollments = new EnrollmentRepository(db);
    this.assignments = new AssignmentRepository(db);
    this.batches = new ImportBatchRepository(db);
    this.users = new UserRepository(db);
  }

  async assertEnrollmentAccess(
    userId: string,
    role: UserRoleType,
    classId: string,
    subjectId: string,
  ): Promise<void> {
    if (role === UserRole.TrainingOfficeAdmin) {
      return;
    }
    if (role === UserRole.Instructor) {
      const assigned = await this.assignments.hasAssignment(
        userId,
        classId,
        subjectId,
      );
      if (!assigned) {
        throw forbidden();
      }
      return;
    }
    throw forbidden();
  }

  async getEnrollments(
    classId: string,
    subjectId: string,
    requesterId: string,
    role: UserRoleType,
  ): Promise<{
    class: ClassRecord;
    subject: SubjectRecord;
    enrollments: EnrollmentRecord[];
    totalCount: number;
  }> {
    await this.assertEnrollmentAccess(requesterId, role, classId, subjectId);

    const classRecord = await this.references.findClassById(classId);
    const subjectRecord = await this.references.findSubjectById(subjectId);
    if (!classRecord || !subjectRecord) {
      throw notFound();
    }

    const enrollmentList = await this.enrollments.listByClassSubject(
      classId,
      subjectId,
    );

    return {
      class: classRecord,
      subject: subjectRecord,
      enrollments: enrollmentList,
      totalCount: enrollmentList.length,
    };
  }

  async listClasses(
    requesterId: string,
    role: UserRoleType,
  ): Promise<ClassRecord[]> {
    if (role === UserRole.TrainingOfficeAdmin) {
      return this.references.listAllClasses();
    }
    if (role === UserRole.Instructor) {
      return this.references.listClassesForInstructor(requesterId);
    }
    throw forbidden();
  }

  async listSubjects(
    requesterId: string,
    role: UserRoleType,
  ): Promise<SubjectRecord[]> {
    if (role === UserRole.TrainingOfficeAdmin) {
      return this.references.listAllSubjects();
    }
    if (role === UserRole.Instructor) {
      return this.references.listSubjectsForInstructor(requesterId);
    }
    throw forbidden();
  }

  async startImport(
    csvBuffer: Buffer,
    options: ImportCsvOptions,
  ): Promise<{ batchId: string; status: typeof RosterImportStatus.Processing }> {
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

    return { batchId, status: RosterImportStatus.Processing };
  }

  async importCsv(
    csvBuffer: Buffer,
    options: ImportCsvOptions,
  ): Promise<ImportSummary> {
    const dryRun = options.dryRun ?? false;
    const batchId = dryRun
      ? randomUUID()
      : await this.batches.createProcessing(
          options.uploadedById,
          options.fileName,
        );
    return this.processImportBatch(batchId, csvBuffer, dryRun, !dryRun);
  }

  async getImportBatch(batchId: string): Promise<ImportSummary | null> {
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
      errorDetails: batch.errorDetails,
    };
  }

  private async processImportBatch(
    batchId: string,
    csvBuffer: Buffer,
    dryRun: boolean,
    persistBatch: boolean,
  ): Promise<ImportSummary> {
    const content = csvBuffer.toString("utf8");
    const { headers, rows } = parseCsvContent(content);
    const mapped = mapCsvRows(headers, rows);

    if (!mapped.ok) {
      const summary = {
        totalRows: rows.length,
        successRows: 0,
        errorRows: rows.length,
        errorDetails: mapped.errors,
      };
      if (persistBatch) {
        await this.batches.complete(batchId, summary);
      }
      return { batchId, status: RosterImportStatus.Completed, ...summary };
    }

    const errorDetails: ImportErrorDetail[] = [];
    let successRows = 0;
    const seenInBatch = new Set<string>();

    const classCache = new Map<string, ClassRecord | null>();
    const subjectCache = new Map<string, SubjectRecord | null>();

    const resolveClass = async (code: string): Promise<ClassRecord | null> => {
      if (!classCache.has(code)) {
        classCache.set(code, await this.references.findClassByCode(code));
      }
      return classCache.get(code) ?? null;
    };

    const resolveSubject = async (code: string): Promise<SubjectRecord | null> => {
      if (!subjectCache.has(code)) {
        subjectCache.set(code, await this.references.findSubjectByCode(code));
      }
      return subjectCache.get(code) ?? null;
    };

    const client = dryRun ? null : await this.db.connect();

    try {
      if (client) {
        await client.query("BEGIN");
      }

      for (const row of mapped.rows) {
        const fieldError = validateRowFields(row);
        if (fieldError) {
          errorDetails.push(fieldError);
          continue;
        }

        const classRecord = await resolveClass(row.classCode.trim());
        if (!classRecord) {
          errorDetails.push({
            rowNumber: row.rowNumber,
            errorCode: RosterRowErrorCode.UnknownClassCode,
            message: ROSTER_ROW_ERROR_MESSAGES[RosterRowErrorCode.UnknownClassCode],
          });
          continue;
        }

        const subjectRecord = await resolveSubject(row.subjectCode.trim());
        if (!subjectRecord) {
          errorDetails.push({
            rowNumber: row.rowNumber,
            errorCode: RosterRowErrorCode.UnknownSubjectCode,
            message: ROSTER_ROW_ERROR_MESSAGES[RosterRowErrorCode.UnknownSubjectCode],
          });
          continue;
        }

        const batchKey = `${row.institutionalId.trim()}|${classRecord.id}|${subjectRecord.id}`;
        if (seenInBatch.has(batchKey)) {
          errorDetails.push({
            rowNumber: row.rowNumber,
            errorCode: RosterRowErrorCode.DuplicateEnrollment,
            message: ROSTER_ROW_ERROR_MESSAGES[RosterRowErrorCode.DuplicateEnrollment],
          });
          continue;
        }
        seenInBatch.add(batchKey);

        let student = await this.users.findByInstitutionalId(
          row.institutionalId.trim(),
        );

        if (dryRun) {
          if (student) {
            const exists = await this.enrollments.exists(
              student.id,
              classRecord.id,
              subjectRecord.id,
            );
            if (exists) {
              errorDetails.push({
                rowNumber: row.rowNumber,
                errorCode: RosterRowErrorCode.DuplicateEnrollment,
                message:
                  ROSTER_ROW_ERROR_MESSAGES[RosterRowErrorCode.DuplicateEnrollment],
              });
              continue;
            }
          }
          successRows += 1;
          continue;
        }

        if (!student && client) {
          const institutionalId = row.institutionalId.trim();
          const email = `${institutionalId.toLowerCase()}@roster.import.local`;
          const passwordHash = await hashPassword(randomUUID());
          const insert = await client.query<{ id: string }>(
            `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
             VALUES ($1, $2, $3, $4, $5, true)
             RETURNING id`,
            [
              institutionalId,
              row.displayName.trim(),
              email,
              passwordHash,
              UserRole.Student,
            ],
          );
          student = {
            id: insert.rows[0]!.id,
            institutionalId,
            displayName: row.displayName.trim(),
            email,
            passwordHash,
            role: UserRole.Student,
            active: true,
            createdAt: new Date(),
            updatedAt: new Date(),
          };
        } else if (student && client && student.displayName !== row.displayName.trim()) {
          await client.query(
            "UPDATE users SET display_name = $1, updated_at = NOW() WHERE id = $2",
            [row.displayName.trim(), student.id],
          );
        }

        if (!student) {
          continue;
        }

        const exists = await this.enrollments.exists(
          student.id,
          classRecord.id,
          subjectRecord.id,
        );
        if (exists) {
          errorDetails.push({
            rowNumber: row.rowNumber,
            errorCode: RosterRowErrorCode.DuplicateEnrollment,
            message: ROSTER_ROW_ERROR_MESSAGES[RosterRowErrorCode.DuplicateEnrollment],
          });
          continue;
        }

        await this.enrollments.create(
          student.id,
          classRecord.id,
          subjectRecord.id,
          client ?? undefined,
        );
        successRows += 1;
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
      errorDetails,
    };

    if (persistBatch) {
      await this.batches.complete(batchId, summary);
    }

    return {
      batchId,
      status: RosterImportStatus.Completed,
      ...summary,
    };
  }
}

export async function truncateRosterTables(db: DbPool): Promise<void> {
  await db.query(`
    TRUNCATE TABLE
      roster_import_batches,
      enrollments,
      class_assignments,
      classes,
      subjects
    RESTART IDENTITY CASCADE
  `);
}
