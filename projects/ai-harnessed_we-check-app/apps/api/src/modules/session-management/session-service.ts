import { randomUUID } from "node:crypto";
import {
  SessionStatus,
  TERMINAL_SESSION_STATUSES,
  UserRole,
  getSessionStatusAfterTransition,
  hasValidRoomGps,
  type UserRole as UserRoleType,
} from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { now } from "../../infra/clock.js";
import {
  forbidden,
  invalidSessionState,
  notFound,
  roomGpsRequired,
  validationFailed,
  ApiError,
} from "../../errors/api-error.js";
import { AssignmentRepository } from "../roster-enrollment/assignment-repository.js";
import { ReferenceRepository } from "../roster-enrollment/reference-repository.js";
import { AttendanceBootstrap } from "./attendance-bootstrap.js";
import { QrScheduler } from "./qr-scheduler.js";
import { SessionRepository } from "./session-repository.js";
import type {
  AttendanceRecordDto,
  AttendanceSummary,
  CreateSessionInput,
  PatchSessionInput,
  QrTokenDisplayDto,
  SessionDto,
  SessionRecord,
} from "./types.js";
import {
  normalizeCreateSession,
  validateCreateSession,
  validatePatchSession,
} from "./validation.js";

export function toSessionDto(
  record: SessionRecord,
  enrollmentCount?: number,
): SessionDto {
  return {
    id: record.id,
    instructorId: record.instructorId,
    classId: record.classId,
    subjectId: record.subjectId,
    title: record.title,
    roomName: record.roomName,
    roomLatitude: record.roomLatitude,
    roomLongitude: record.roomLongitude,
    gpsRadiusMeters: record.gpsRadiusMeters,
    scheduledStart: record.scheduledStart.toISOString(),
    status: record.status,
    openedAt: record.openedAt?.toISOString() ?? null,
    closedAt: record.closedAt?.toISOString() ?? null,
    ...(enrollmentCount !== undefined ? { enrollmentCount } : {}),
  };
}

export class SessionService {
  private readonly sessions: SessionRepository;
  private readonly attendance: AttendanceBootstrap;
  private readonly references: ReferenceRepository;
  private readonly assignments: AssignmentRepository;
  readonly qr: QrScheduler;

  constructor(private readonly db: DbPool) {
    this.sessions = new SessionRepository(db);
    this.attendance = new AttendanceBootstrap(db);
    this.references = new ReferenceRepository(db);
    this.assignments = new AssignmentRepository(db);
    this.qr = new QrScheduler(db);
  }

  async assertWriteAccess(
    userId: string,
    role: UserRoleType,
    classId: string,
    subjectId: string,
    sessionInstructorId?: string,
  ): Promise<void> {
    if (role !== UserRole.Instructor) {
      throw forbidden();
    }
    const assigned = await this.assignments.hasAssignment(
      userId,
      classId,
      subjectId,
    );
    if (!assigned) {
      throw forbidden();
    }
    if (sessionInstructorId !== undefined && sessionInstructorId !== userId) {
      throw forbidden();
    }
  }

  async assertReadAccess(
    userId: string,
    role: UserRoleType,
    session: SessionRecord,
  ): Promise<void> {
    if (role === UserRole.TrainingOfficeAdmin) {
      return;
    }
    if (role === UserRole.Instructor) {
      if (session.instructorId === userId) {
        return;
      }
      const assigned = await this.assignments.hasAssignment(
        userId,
        session.classId,
        session.subjectId,
      );
      if (!assigned) {
        throw forbidden();
      }
      return;
    }
    throw forbidden();
  }

  async create(
    input: CreateSessionInput,
    instructorId: string,
    role: UserRoleType,
  ): Promise<SessionDto> {
    const errors = validateCreateSession(input);
    if (errors.length > 0) {
      throw validationFailed(errors);
    }

    const normalized = normalizeCreateSession(input);
    await this.assertWriteAccess(
      instructorId,
      role,
      normalized.classId,
      normalized.subjectId,
    );

    const classRecord = await this.references.findClassById(normalized.classId);
    const subjectRecord = await this.references.findSubjectById(
      normalized.subjectId,
    );
    if (!classRecord || !subjectRecord) {
      throw notFound();
    }

    const record = await this.sessions.insert({
      id: randomUUID(),
      instructorId,
      classId: normalized.classId,
      subjectId: normalized.subjectId,
      title: normalized.title,
      roomName: normalized.roomName,
      roomLatitude: normalized.roomLatitude ?? null,
      roomLongitude: normalized.roomLongitude ?? null,
      gpsRadiusMeters: normalized.gpsRadiusMeters!,
      scheduledStart: new Date(normalized.scheduledStart),
      status: SessionStatus.Draft,
      openedAt: null,
      closedAt: null,
    });

    return toSessionDto(record);
  }

  async patch(
    sessionId: string,
    input: PatchSessionInput,
    userId: string,
    role: UserRoleType,
  ): Promise<SessionDto> {
    const errors = validatePatchSession(input);
    if (errors.length > 0) {
      throw validationFailed(errors);
    }

    const existing = await this.sessions.findById(sessionId);
    if (!existing) {
      throw notFound();
    }

    if (TERMINAL_SESSION_STATUSES.has(existing.status) || existing.status === SessionStatus.Active) {
      throw invalidSessionState();
    }

    await this.assertWriteAccess(
      userId,
      role,
      existing.classId,
      existing.subjectId,
      existing.instructorId,
    );

    const updated = await this.sessions.update(
      sessionId,
      {
        ...(input.title !== undefined ? { title: input.title.trim() } : {}),
        ...(input.roomName !== undefined
          ? { roomName: input.roomName.trim() }
          : {}),
        ...(input.roomLatitude !== undefined
          ? { roomLatitude: input.roomLatitude }
          : {}),
        ...(input.roomLongitude !== undefined
          ? { roomLongitude: input.roomLongitude }
          : {}),
        ...(input.gpsRadiusMeters !== undefined
          ? { gpsRadiusMeters: input.gpsRadiusMeters }
          : {}),
        ...(input.scheduledStart !== undefined
          ? { scheduledStart: new Date(input.scheduledStart) }
          : {}),
      },
      existing.version,
    );

    if (!updated) {
      throw invalidSessionState();
    }

    return toSessionDto(updated);
  }

  async getById(
    sessionId: string,
    userId: string,
    role: UserRoleType,
  ): Promise<SessionDto> {
    const session = await this.sessions.findById(sessionId);
    if (!session) {
      throw notFound();
    }
    await this.assertReadAccess(userId, role, session);
    const enrollmentCount = await this.attendance.countForSession(sessionId);
    return toSessionDto(session, enrollmentCount);
  }

  async open(
    sessionId: string,
    userId: string,
    role: UserRoleType,
  ): Promise<SessionDto> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");

      const existing = await this.sessions.findByIdForUpdate(client, sessionId);
      if (!existing) {
        throw notFound();
      }

      await this.assertWriteAccess(
        userId,
        role,
        existing.classId,
        existing.subjectId,
        existing.instructorId,
      );

      if (existing.status !== SessionStatus.Draft) {
        throw invalidSessionState();
      }

      if (
        !hasValidRoomGps({
          roomLatitude: existing.roomLatitude,
          roomLongitude: existing.roomLongitude,
        })
      ) {
        throw roomGpsRequired();
      }

      const openedAt = now();
      getSessionStatusAfterTransition(existing.status, "open");

      const updated = await this.sessions.update(
        sessionId,
        {
          status: SessionStatus.Active,
          openedAt,
        },
        existing.version,
        client,
      );

      if (!updated) {
        throw invalidSessionState();
      }

      await this.attendance.initializeForSession(
        client,
        sessionId,
        existing.classId,
        existing.subjectId,
      );

      await client.query("COMMIT");

      this.qr.start(sessionId);
      await this.qr.rotate(sessionId);

      return toSessionDto(updated);
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async close(
    sessionId: string,
    userId: string,
    role: UserRoleType,
  ): Promise<SessionDto> {
    return this.finalizeClose(sessionId, userId, role);
  }

  async autoClose(sessionId: string): Promise<boolean> {
    try {
      await this.finalizeClose(sessionId, undefined, undefined, true);
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.errorCode === "InvalidSessionState") {
        return false;
      }
      throw error;
    }
  }

  private async finalizeClose(
    sessionId: string,
    userId: string | undefined,
    role: UserRoleType | undefined,
    isAuto = false,
  ): Promise<SessionDto> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");

      const existing = await this.sessions.findByIdForUpdate(client, sessionId);
      if (!existing) {
        throw notFound();
      }

      if (!isAuto && userId !== undefined && role !== undefined) {
        await this.assertWriteAccess(
          userId,
          role,
          existing.classId,
          existing.subjectId,
          existing.instructorId,
        );
      }

      if (existing.status !== SessionStatus.Active) {
        throw invalidSessionState();
      }

      getSessionStatusAfterTransition(existing.status, "close");

      const closedAt = now();
      const updated = await this.sessions.update(
        sessionId,
        {
          status: SessionStatus.Closed,
          closedAt,
        },
        existing.version,
        client,
      );

      if (!updated) {
        throw invalidSessionState();
      }

      await this.attendance.finalizeOnClose(client, sessionId);

      await client.query("COMMIT");

      this.qr.stop(sessionId);

      return toSessionDto(updated);
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async cancel(
    sessionId: string,
    userId: string,
    role: UserRoleType,
  ): Promise<SessionDto> {
    const existing = await this.sessions.findById(sessionId);
    if (!existing) {
      throw notFound();
    }

    await this.assertWriteAccess(
      userId,
      role,
      existing.classId,
      existing.subjectId,
      existing.instructorId,
    );

    if (existing.status !== SessionStatus.Draft) {
      throw invalidSessionState();
    }

    getSessionStatusAfterTransition(existing.status, "cancel");

    const updated = await this.sessions.update(
      sessionId,
      { status: SessionStatus.Cancelled },
      existing.version,
    );

    if (!updated) {
      throw invalidSessionState();
    }

    return toSessionDto(updated);
  }

  async getAttendance(
    sessionId: string,
    userId: string,
    role: UserRoleType,
  ): Promise<{ summary: AttendanceSummary; records: AttendanceRecordDto[] }> {
    const session = await this.sessions.findById(sessionId);
    if (!session) {
      throw notFound();
    }
    await this.assertReadAccess(userId, role, session);

    const [summary, records] = await Promise.all([
      this.attendance.getSummary(sessionId),
      this.attendance.listRecords(sessionId),
    ]);

    return { summary, records };
  }

  async getCurrentQr(
    sessionId: string,
    userId: string,
    role: UserRoleType,
  ): Promise<QrTokenDisplayDto> {
    const session = await this.sessions.findById(sessionId);
    if (!session) {
      throw notFound();
    }

    if (role === UserRole.Instructor) {
      await this.assertWriteAccess(
        userId,
        role,
        session.classId,
        session.subjectId,
        session.instructorId,
      );
    } else if (role !== UserRole.TrainingOfficeAdmin) {
      throw forbidden();
    }

    if (session.status !== SessionStatus.Active) {
      throw invalidSessionState();
    }

    const token = await this.qr.getCurrentToken(
      sessionId,
      session.scheduledStart,
    );
    if (!token) {
      throw invalidSessionState();
    }

    return token;
  }
}

export async function truncateSessionTables(db: DbPool): Promise<void> {
  await db.query(
    "TRUNCATE qr_tokens, attendance_records, sessions RESTART IDENTITY CASCADE",
  );
}
