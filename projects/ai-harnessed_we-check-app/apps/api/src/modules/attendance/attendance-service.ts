import {
  AttendanceStatus,
  UserRole,
  type UserRole as UserRoleType,
} from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { now } from "../../infra/clock.js";
import {
  editWindowExpired,
  forbidden,
  invalidPagination,
  notFound,
  ApiError,
} from "../../errors/api-error.js";
import { AssignmentRepository } from "../roster-enrollment/assignment-repository.js";
import { AttendanceRepository } from "./attendance-repository.js";
import { AuditRepository } from "./audit-repository.js";
import { assertManualEditAllowed } from "./edit-window-policy.js";
import type {
  AttendanceRecordDto,
  AttendanceSummary,
  ManualEditInput,
  StudentHistoryItemDto,
  StudentHistoryQuery,
} from "./types.js";

const MANUAL_EDIT_STATUSES = new Set<AttendanceStatus>([
  AttendanceStatus.Present,
  AttendanceStatus.Absent,
  AttendanceStatus.Excused,
  AttendanceStatus.Rejected,
]);

export class AttendanceService {
  private readonly records: AttendanceRepository;
  private readonly audit: AuditRepository;
  private readonly assignments: AssignmentRepository;

  constructor(private readonly db: DbPool) {
    this.records = new AttendanceRepository(db);
    this.audit = new AuditRepository(db);
    this.assignments = new AssignmentRepository(db);
  }

  initializeForSession(
    client: { query: DbPool["query"] },
    sessionId: string,
    classId: string,
    subjectId: string,
  ): Promise<number> {
    return this.records.initializeForSession(
      client,
      sessionId,
      classId,
      subjectId,
    );
  }

  finalizeOnClose(
    client: { query: DbPool["query"] },
    sessionId: string,
  ): Promise<number> {
    return this.records.finalizeOnClose(client, sessionId);
  }

  getSummary(sessionId: string): Promise<AttendanceSummary> {
    return this.records.getSummary(sessionId);
  }

  async listRecords(sessionId: string): Promise<
    Array<{
      id: string;
      studentId: string;
      institutionalId: string;
      displayName: string;
      status: AttendanceStatus;
      checkedInAt: string | null;
    }>
  > {
    return this.records.listRecords(sessionId);
  }

  countForSession(sessionId: string): Promise<number> {
    return this.records.countForSession(sessionId);
  }

  async assertWriteAccess(
    userId: string,
    role: UserRoleType,
    session: {
      classId: string;
      subjectId: string;
    },
  ): Promise<void> {
    if (role === UserRole.TrainingOfficeAdmin) {
      return;
    }
    if (role !== UserRole.Instructor) {
      throw forbidden();
    }
    const assigned = await this.assignments.hasAssignment(
      userId,
      session.classId,
      session.subjectId,
    );
    if (!assigned) {
      throw forbidden();
    }
  }

  async manualEdit(
    recordId: string,
    input: ManualEditInput,
    editorId: string,
    editorRole: UserRoleType,
  ): Promise<AttendanceRecordDto> {
    if (!MANUAL_EDIT_STATUSES.has(input.status)) {
      throw forbidden();
    }

    const existing = await this.records.findRecordById(recordId);
    if (!existing) {
      throw notFound();
    }

    const session = await this.records.findSessionContext(existing.sessionId);
    if (!session) {
      throw notFound();
    }

    await this.assertWriteAccess(editorId, editorRole, session);

    const editAllowed = assertManualEditAllowed({
      editorRole,
      sessionStatus: session.status,
      closedAt: session.closedAt,
      now: now(),
    });
    if (!editAllowed) {
      throw editWindowExpired();
    }

    const checkedInAt =
      input.status === AttendanceStatus.Present
        ? (existing.checkedInAt ?? now())
        : null;

    const client = await this.db.connect();
    try {
      await client.query("BEGIN");

      const updated = await this.records.updateStatus(
        client,
        recordId,
        input.status,
        checkedInAt,
        existing.version,
      );
      if (!updated) {
        throw notFound();
      }

      await this.audit.insertManualEdit(client, {
        attendanceRecordId: recordId,
        editorId,
        previousStatus: existing.status,
        newStatus: input.status,
        note: input.note?.trim() ?? null,
        editedAt: now(),
      });

      await client.query("COMMIT");

      return {
        id: updated.id,
        sessionId: updated.sessionId,
        studentId: existing.studentId,
        institutionalId: existing.institutionalId,
        displayName: existing.displayName,
        status: updated.status,
        checkedInAt: updated.checkedInAt?.toISOString() ?? null,
      };
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async getAuditLogs(
    recordId: string,
    userId: string,
    role: UserRoleType,
  ): Promise<{
    items: Array<{
      id: string;
      editorId: string;
      editorDisplayName: string;
      previousStatus: AttendanceStatus;
      newStatus: AttendanceStatus;
      note: string | null;
      editedAt: string;
    }>;
  }> {
    const existing = await this.records.findRecordById(recordId);
    if (!existing) {
      throw notFound();
    }

    const session = await this.records.findSessionContext(existing.sessionId);
    if (!session) {
      throw notFound();
    }

    if (role === UserRole.Student) {
      throw forbidden();
    }

    if (role === UserRole.Instructor) {
      await this.assertWriteAccess(userId, role, session);
    }

    const items = await this.audit.listForRecord(recordId);
    return {
      items: items.map((entry) => ({
        ...entry,
        editedAt: entry.editedAt.toISOString(),
      })),
    };
  }

  async getStudentHistory(
    studentId: string,
    query: StudentHistoryQuery,
  ): Promise<{
    items: StudentHistoryItemDto[];
    nextCursor: string | null;
    totalCount: number;
  }> {
    let cursor: { scheduledStart: string; sessionId: string } | undefined;
    if (query.cursor) {
      try {
        const decoded = JSON.parse(
          Buffer.from(query.cursor, "base64url").toString("utf8"),
        ) as { scheduledStart: string; sessionId: string };
        if (!decoded.scheduledStart || !decoded.sessionId) {
          throw invalidPagination();
        }
        cursor = decoded;
      } catch (error) {
        if (error instanceof ApiError) {
          throw error;
        }
        throw invalidPagination();
      }
    }

    const filters = {
      subjectId: query.subjectId,
      from: query.from,
      to: query.to,
    };

    const [totalCount, page] = await Promise.all([
      this.records.countStudentHistory(studentId, filters),
      this.records.listStudentHistory(studentId, {
        ...filters,
        limit: query.limit,
        cursor,
      }),
    ]);

    const last = page.items[page.items.length - 1];
    const nextCursor =
      page.hasMore && last
        ? Buffer.from(
            JSON.stringify({
              scheduledStart: last.sessionDate,
              sessionId: last.sessionId,
            }),
          ).toString("base64url")
        : null;

    return { items: page.items, nextCursor, totalCount };
  }

  async markPresent(
    client: { query: DbPool["query"] },
    sessionId: string,
    studentId: string,
    checkedInAt: Date,
  ): Promise<void> {
    await client.query(
      `UPDATE attendance_records
       SET status = $3, checked_in_at = $4, updated_at = NOW(), version = version + 1
       WHERE session_id = $1 AND student_id = $2`,
      [sessionId, studentId, AttendanceStatus.Present, checkedInAt],
    );
  }
}

export async function truncateAttendanceTables(db: DbPool): Promise<void> {
  await db.query(
    "TRUNCATE attendance_audit_logs, qr_tokens, attendance_records, sessions RESTART IDENTITY CASCADE",
  );
}
