/**
 * Traceability: FR-09 FR-20 FR-21 BR-13 BR-14 BR-15 BR-16 AC-12 AC-13 AC-14
 * TC-AC-12-002 TC-AC-12-005 TC-AC-13-002 TC-AC-13-005 TC-FR-09-002 TC-FR-20-002 TC-FR-20-012 TC-FR-21-002 TC-FR-21-003 TC-BR-14-006
 */
import { randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";

const SEED = {
  section: "50000000-0000-4000-8000-000000000001",
  room: "40000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
  student2: "60000000-0000-4000-8000-000000000003",
  student3: "60000000-0000-4000-8000-000000000004",
  academicAdmin: "60000000-0000-4000-8000-000000000005",
};

async function waitForSeededDb(client: pg.Client, attempts = 60): Promise<void> {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const users = await client.query(`SELECT 1 FROM users LIMIT 1`);
      const creds = await client.query(`SELECT 1 FROM user_credentials LIMIT 1`);
      if ((users.rowCount ?? 0) > 0 && (creds.rowCount ?? 0) > 0) {
        return;
      }
    } catch {
      // schema may still be migrating
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Timed out waiting for migrated and seeded test database");
}

async function login(app: FastifyInstance, email: string): Promise<string> {
  const response = await app.inject({
    method: "POST",
    url: "/api/v1/auth/login",
    payload: { email, password: TEST_PASSWORD },
  });
  expect(response.statusCode).toBe(200);
  return (response.json() as { data: { accessToken: string } }).data.accessToken;
}

async function insertSession(
  pool: pg.Pool,
  state: "Scheduled" | "Open" | "Closed",
  closedAt?: Date,
): Promise<string> {
  const sessionId = randomUUID();
  const start = new Date();
  const end = new Date(start.getTime() + 90 * 60_000);

  if (state === "Open") {
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
        state, opened_at, opened_by_user_id
      )
      VALUES ($1, $2, $3, $4, $5, 'Open', $6, $7)
      `,
      [sessionId, SEED.section, SEED.room, start, end, start, SEED.lecturer],
    );
  } else if (state === "Closed") {
    const closed = closedAt ?? end;
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
        state, opened_at, opened_by_user_id, closed_at, closed_by_user_id
      )
      VALUES ($1, $2, $3, $4, $5, 'Closed', $6, $7, $8, $7)
      `,
      [sessionId, SEED.section, SEED.room, start, end, start, SEED.lecturer, closed],
    );
  } else {
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at, state
      )
      VALUES ($1, $2, $3, $4, $5, 'Scheduled')
      `,
      [sessionId, SEED.section, SEED.room, start, end],
    );
  }

  return sessionId;
}

async function cleanupSession(pool: pg.Pool, sessionId: string) {
  await pool.query(`DELETE FROM audit_logs WHERE target_id IN (
    SELECT id FROM attendance_records WHERE class_session_id = $1
  )`, [sessionId]);
  await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM check_in_attempts WHERE class_session_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM class_sessions WHERE id = $1`, [sessionId]);
}

describe("M05 attendance ledger — FR-09 FR-20 FR-21 BR-13 BR-14 AC-12 AC-13", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
  const createdSessions: string[] = [];

  beforeAll(async () => {
    expect(databaseUrl).toBeTruthy();
    process.env.DATABASE_URL = databaseUrl;
    process.env.JWT_SECRET = "test-jwt";
    const probe = new pg.Client({ connectionString: databaseUrl });
    await probe.connect();
    await waitForSeededDb(probe);
    await probe.end();
    app = await buildApp();
    await app.ready();
    pool = new pg.Pool({ connectionString: databaseUrl });
  });

  afterEach(async () => {
    for (const sessionId of createdSessions.splice(0)) {
      await cleanupSession(pool, sessionId);
    }
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  function track(sessionId: string): string {
    createdSessions.push(sessionId);
    return sessionId;
  }

  it("TC-AC-12-002 TC-FR-09-002: close finalizes Pending and missing students as Absent while preserving Present", async () => {
    const sessionId = track(await insertSession(pool, "Scheduled"));
    const lecturerToken = await login(app, "lecturer@attendly.local");

    const openResponse = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/open`,
      headers: { authorization: `Bearer ${lecturerToken}`, "idempotency-key": randomUUID() },
    });
    expect(openResponse.statusCode).toBe(200);

    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status,
        check_in_method, check_in_at, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Present', 'QR', now(), $4)
      `,
      [randomUUID(), sessionId, SEED.section, SEED.student],
    );

    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Pending', $5)
      `,
      [randomUUID(), sessionId, SEED.section, SEED.student2, SEED.lecturer],
    );

    const closeResponse = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/close`,
      headers: { authorization: `Bearer ${lecturerToken}`, "idempotency-key": randomUUID() },
    });
    expect(closeResponse.statusCode).toBe(200);

    const rosterResponse = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/attendance`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });
    expect(rosterResponse.statusCode).toBe(200);

    const roster = (rosterResponse.json() as { data: { rows: { studentUserId: string; attendanceStatus: string }[] } }).data;
    const presentRow = roster.rows.find((row) => row.studentUserId === SEED.student);
    const pendingRow = roster.rows.find((row) => row.studentUserId === SEED.student2);
    expect(presentRow?.attendanceStatus).toBe("Present");
    expect(pendingRow?.attendanceStatus).toBe("Absent");

    const absentCount = await pool.query(
      `SELECT COUNT(*)::int AS count FROM attendance_records WHERE class_session_id = $1 AND status = 'Absent'`,
      [sessionId],
    );
    expect(absentCount.rows[0]?.count).toBeGreaterThan(0);

    const absentAudits = await pool.query<{ actor_user_id: string | null; count: string }>(
      `
      SELECT actor_user_id, COUNT(*)::text AS count
      FROM audit_logs
      WHERE action_type = 'AttendanceUpdate'
        AND target_id IN (
          SELECT id FROM attendance_records
          WHERE class_session_id = $1 AND status = 'Absent'
        )
      GROUP BY actor_user_id
      `,
      [sessionId],
    );
    expect(absentAudits.rows.some((row) => row.actor_user_id === null)).toBe(true);
    const totalAbsentAudits = absentAudits.rows.reduce(
      (sum, row) => sum + Number.parseInt(row.count, 10),
      0,
    );
    expect(totalAbsentAudits).toBeGreaterThanOrEqual(absentCount.rows[0]?.count ?? 0);
  });

  it("TC-AC-13-002 TC-FR-20-002: lecturer manual correction within window writes audit row", async () => {
    const closedAt = new Date();
    const sessionId = track(await insertSession(pool, "Closed", closedAt));
    const lecturerToken = await login(app, "lecturer@attendly.local");

    const recordId = randomUUID();
    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Absent', $5)
      `,
      [recordId, sessionId, SEED.section, SEED.student, SEED.lecturer],
    );

    const patchResponse = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${sessionId}/attendance/${SEED.student}`,
      headers: {
        authorization: `Bearer ${lecturerToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        status: "Manual Present",
        reason: "Sinh vien co mat nhung loi camera tren thiet bi.",
      },
    });
    expect(patchResponse.statusCode).toBe(200);

    const body = patchResponse.json() as {
      data: { attendanceStatus: string; checkInMethod: string };
    };
    expect(body.data.attendanceStatus).toBe("Manual Present");
    expect(body.data.checkInMethod).toBe("Manual");

    const audit = await pool.query(
      `SELECT COUNT(*)::int AS count FROM audit_logs WHERE target_id = $1 AND action_type = 'AttendanceUpdate'`,
      [recordId],
    );
    expect(audit.rows[0]?.count).toBe(1);
  });

  it("TC-FR-20-012 TC-BR-14-006 TC-AC-14: lecturer denied after edit window expires (BR-15)", async () => {
    const closedAt = new Date(Date.now() - 48 * 60 * 60 * 1000);
    const sessionId = track(await insertSession(pool, "Closed", closedAt));
    const lecturerToken = await login(app, "lecturer@attendly.local");
    const adminToken = await login(app, "academic-admin@attendly.local");

    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Absent', $5)
      `,
      [randomUUID(), sessionId, SEED.section, SEED.student, SEED.lecturer],
    );

    const lecturerDenied = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${sessionId}/attendance/${SEED.student}`,
      headers: {
        authorization: `Bearer ${lecturerToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: { status: "Manual Present", reason: "Late correction attempt." },
    });
    expect(lecturerDenied.statusCode).toBe(409);
    expect((lecturerDenied.json() as { error: { code: string } }).error.code).toBe("EditWindowExpired");

    const adminPatch = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${sessionId}/attendance/${SEED.student}`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        status: "Excused",
        reason: "Giai quyet khieu nai sau khi het han chinh sua cua giang vien.",
      },
    });
    expect(adminPatch.statusCode).toBe(200);
    expect((adminPatch.json() as { data: { checkInMethod: string; attendanceStatus: string } }).data).toMatchObject({
      checkInMethod: "Admin Correction",
      attendanceStatus: "Excused",
    });
  });

  it("TC-AC-13-009 TC-FR-20-013: rejects correction without reason", async () => {
    const sessionId = track(await insertSession(pool, "Closed"));
    const lecturerToken = await login(app, "lecturer@attendly.local");

    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Absent', $5)
      `,
      [randomUUID(), sessionId, SEED.section, SEED.student, SEED.lecturer],
    );

    const response = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${sessionId}/attendance/${SEED.student}`,
      headers: {
        authorization: `Bearer ${lecturerToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: { status: "Manual Present", reason: "" },
    });
    expect(response.statusCode).toBe(400);
    expect((response.json() as { error: { code: string } }).error.code).toBe("ReasonRequired");
  });

  it("TC-AC-12-007 TC-BR-13-007: close preserves Excused and Manual Present while finalizing Pending", async () => {
    const sessionId = track(await insertSession(pool, "Scheduled"));
    const lecturerToken = await login(app, "lecturer@attendly.local");

    const openResponse = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/open`,
      headers: { authorization: `Bearer ${lecturerToken}`, "idempotency-key": randomUUID() },
    });
    expect(openResponse.statusCode).toBe(200);

    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status,
        check_in_method, last_modified_by_user_id, modification_reason
      )
      VALUES
        ($1, $2, $3, $4, 'Excused', 'Manual', $5, 'Co phep nghi hoc.'),
        ($6, $2, $3, $7, 'Manual Present', 'Manual', $5, 'Xac nhan co mat thu cong.'),
        ($8, $2, $3, $9, 'Pending', NULL, $5, NULL)
      `,
      [
        randomUUID(), sessionId, SEED.section, SEED.student, SEED.lecturer,
        randomUUID(), SEED.student2,
        randomUUID(), SEED.student3,
      ],
    );

    const closeResponse = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/close`,
      headers: { authorization: `Bearer ${lecturerToken}`, "idempotency-key": randomUUID() },
    });
    expect(closeResponse.statusCode).toBe(200);

    const rosterResponse = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/attendance`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });
    const roster = (rosterResponse.json() as { data: { rows: { studentUserId: string; attendanceStatus: string }[] } }).data;
    expect(roster.rows.find((row) => row.studentUserId === SEED.student)?.attendanceStatus).toBe("Excused");
    expect(roster.rows.find((row) => row.studentUserId === SEED.student2)?.attendanceStatus).toBe("Manual Present");
    expect(roster.rows.find((row) => row.studentUserId === SEED.student3)?.attendanceStatus).toBe("Absent");
  });

  it("TC-AC-13-004 TC-BR-14-008: idempotent correction replay returns same result without duplicate audit", async () => {
    const closedAt = new Date();
    const sessionId = track(await insertSession(pool, "Closed", closedAt));
    const lecturerToken = await login(app, "lecturer@attendly.local");
    const idempotencyKey = randomUUID();

    const recordId = randomUUID();
    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Absent', $5)
      `,
      [recordId, sessionId, SEED.section, SEED.student, SEED.lecturer],
    );

    const payload = {
      status: "Manual Present",
      reason: "Idempotent correction replay test.",
    };
    const headers = {
      authorization: `Bearer ${lecturerToken}`,
      "idempotency-key": idempotencyKey,
    };

    const first = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${sessionId}/attendance/${SEED.student}`,
      headers,
      payload,
    });
    expect(first.statusCode).toBe(200);

    const second = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${sessionId}/attendance/${SEED.student}`,
      headers,
      payload,
    });
    expect(second.statusCode).toBe(200);
    expect((second.json() as { data: unknown }).data).toEqual((first.json() as { data: unknown }).data);

    const audit = await pool.query(
      `SELECT COUNT(*)::int AS count FROM audit_logs WHERE target_id = $1 AND action_type = 'AttendanceUpdate'`,
      [recordId],
    );
    expect(audit.rows[0]?.count).toBe(1);
  });

  it("TC-FR-09-002: QR check-in success upserts Pending record to Present", async () => {
    const sessionId = track(await insertSession(pool, "Open"));
    const { createAttendanceLedgerRepository } = await import("./repository.js");
    const ledger = createAttendanceLedgerRepository(pool);
    const client = await pool.connect();
    const recordId = randomUUID();
    const attemptId = randomUUID();

    try {
      await client.query("BEGIN");
      await client.query(
        `
        INSERT INTO check_in_attempts (
          id, class_session_id, student_user_id, outcome, submitted_at
        )
        VALUES ($1, $2, $3, 'Success', now())
        `,
        [attemptId, sessionId, SEED.student],
      );
      await client.query(
        `
        INSERT INTO attendance_records (
          id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
        )
        VALUES ($1, $2, $3, $4, 'Pending', $5)
        `,
        [recordId, sessionId, SEED.section, SEED.student, SEED.lecturer],
      );

      const checkInAt = await ledger.recordCheckInSuccess(client, {
        classSessionId: sessionId,
        classSectionId: SEED.section,
        studentUserId: SEED.student,
        status: "Present",
        checkInAt: new Date(),
        sourceAttemptId: attemptId,
      });
      expect(checkInAt).toBeTruthy();
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }

    const record = await pool.query<{ status: string; check_in_method: string }>(
      `SELECT status, check_in_method FROM attendance_records WHERE id = $1`,
      [recordId],
    );
    expect(record.rows[0]).toMatchObject({ status: "Present", check_in_method: "QR" });

    const audit = await pool.query(
      `SELECT COUNT(*)::int AS count FROM audit_logs WHERE target_id = $1 AND action_type = 'AttendanceUpdate'`,
      [recordId],
    );
    expect(audit.rows[0]?.count).toBe(1);
  });
});
