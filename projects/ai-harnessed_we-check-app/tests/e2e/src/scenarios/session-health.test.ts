import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { AttendanceStatus, SessionStatus } from "@wecheck/domain";
import { createPool } from "../../../../apps/api/src/infra/db.js";
import { buildApp } from "../../../../apps/api/src/server.js";
import { ctx } from "../support/e2e-context.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

/**
 * Session health contract during Active attendance window (NFR-01, NFR-22)
 * Cases: TC-NFR-01-003 TC-NFR-01-010
 */
describe("Session health during Active window (NFR-01, NFR-22, FR-05)", () => {
  before(async () => {
    await ctx.setup();
  });

  after(async () => {
    await ctx.teardown();
  });

  async function assertHealthOk(): Promise<void> {
    const response = await ctx.app.inject({ method: "GET", url: "/api/v1/health" });
    assert.equal(response.statusCode, 200);
    const body = response.json<{ status: string; db: string }>();
    assert.equal(body.status, "ok");
    assert.equal(body.db, "connected");
  }

  async function seedActiveSessionWithEnrollment(): Promise<{
    sessionId: string;
    studentId: string;
  }> {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const student = await ctx.seedStudent("SV-HEALTH-001", "student-health@example.edu.vn");
    await ctx.enrollStudent(student.userId);

    const sessionId = await ctx.createDraftSession(instructor);
    await ctx.openSession(sessionId, instructor);

    return { sessionId, studentId: student.userId };
  }

  it("GET /api/v1/health stays ok with db connected during Active session window (TC-NFR-01-003, NFR-01, NFR-22, FR-05)", async () => {
    await seedActiveSessionWithEnrollment();

    const pollCount = 12;
    for (let i = 0; i < pollCount; i += 1) {
      await assertHealthOk();
      if (i < pollCount - 1) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }
  });

  it("db disconnect surfaces 503 health; recovery preserves Active session (TC-NFR-01-010, NFR-01, NFR-22, FR-05)", async () => {
    const { sessionId, studentId } = await seedActiveSessionWithEnrollment();

    await assertHealthOk();

    const deadPool = createPool(DEFAULT_DATABASE_URL);
    await deadPool.end();
    const degradedApp = await buildApp({ db: deadPool, logger: false });

    const degradedHealth = await degradedApp.inject({
      method: "GET",
      url: "/api/v1/health",
    });
    assert.equal(degradedHealth.statusCode, 503);
    const degradedBody = degradedHealth.json<{ status: string; db: string }>();
    assert.equal(degradedBody.status, "degraded");
    assert.equal(degradedBody.db, "disconnected");
    await degradedApp.close();

    const pendingBefore = await ctx.db.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM attendance_records
       WHERE session_id = $1 AND status = $2`,
      [sessionId, AttendanceStatus.Pending],
    );
    assert.equal(pendingBefore.rows[0]?.count, 1);

    const presentBefore = await ctx.db.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM attendance_records
       WHERE session_id = $1 AND status = $2`,
      [sessionId, AttendanceStatus.Present],
    );
    assert.equal(presentBefore.rows[0]?.count, 0);

    await assertHealthOk();

    const sessionRow = await ctx.db.query<{ status: string }>(
      `SELECT status FROM sessions WHERE id = $1`,
      [sessionId],
    );
    assert.equal(sessionRow.rows[0]?.status, SessionStatus.Active);

    await ctx.db.query(
      `UPDATE attendance_records SET status = $2, checked_in_at = NOW()
       WHERE session_id = $1 AND student_id = $3 AND status = $4`,
      [sessionId, AttendanceStatus.Present, studentId, AttendanceStatus.Pending],
    );

    const presentAfter = await ctx.db.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM attendance_records
       WHERE session_id = $1 AND status = $2`,
      [sessionId, AttendanceStatus.Present],
    );
    assert.equal(presentAfter.rows[0]?.count, 1);
  });
});
