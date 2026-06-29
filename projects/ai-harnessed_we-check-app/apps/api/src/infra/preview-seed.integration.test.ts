import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { ErrorCode, QrTokenStatus, SessionStatus } from "@wecheck/domain";
import { createPool, setPool, closePool, type DbPool } from "./db.js";
import { runMigrations } from "./migrate.js";
import {
  PREVIEW_CREDENTIALS,
  PREVIEW_IDS,
  ensurePreviewMonitorFixtures,
  ensurePreviewReferenceData,
  ensurePreviewTokenFixtures,
  runPreviewSeed,
} from "./preview-seed.js";
import { truncateRosterTables } from "../modules/roster-enrollment/roster-service.js";
import { truncateCheckInTables } from "../modules/checkin-qr/check-in-service.js";
import { truncateSessionTables } from "../modules/session-management/session-service.js";
import { truncateReportingTables } from "../modules/reporting-export/repositories.js";
import { truncateNotificationTables } from "../modules/notifications/repositories.js";
import { ApiError } from "../errors/api-error.js";
import { withIntegrationTestDbReset } from "../infra/integration-test-lock.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

/** NFR-17 / NFR-06 — preview seed fixtures for browser gates */
describe("preview seed (NFR-17, NFR-06)", () => {
  let db: DbPool;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
  });

  after(async () => {
    await closePool();
  });

  async function resetDb(afterTruncate?: () => Promise<void>): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateCheckInTables(db);
      await truncateSessionTables(db);
      await truncateReportingTables(db);
      await truncateNotificationTables(db);
      await truncateRosterTables(db);
      await db.query("DELETE FROM auth_sessions");
      await db.query("DELETE FROM user_audit_logs");
      await db.query(
        "UPDATE policy_settings SET updated_by_id = NULL WHERE updated_by_id IS NOT NULL",
      );
      await db.query("DELETE FROM users");
      await db.query("DELETE FROM policy_settings WHERE key = 'preview_seed_version'");
      if (afterTruncate) await afterTruncate();
    });
  }

  it("seeds deactivated user and stale QR token for browser fixtures", async () => {
    await resetDb(() => runPreviewSeed(db));

    const deactivatedLogin = await db.query<{ active: boolean }>(
      "SELECT active FROM users WHERE email = $1",
      [PREVIEW_CREDENTIALS.deactivated.email],
    );
    assert.equal(deactivatedLogin.rows[0]?.active, false);

    const staleToken = await db.query<{ status: string; session_id: string }>(
      "SELECT status, session_id FROM qr_tokens WHERE id = $1",
      [PREVIEW_IDS.staleQrToken],
    );
    assert.equal(staleToken.rows[0]?.status, QrTokenStatus.Expired);
    assert.equal(staleToken.rows[0]?.session_id, PREVIEW_IDS.sessionActive);

    const activeSession = await db.query<{ status: string }>(
      "SELECT status FROM sessions WHERE id = $1",
      [PREVIEW_IDS.sessionActive],
    );
    assert.equal(activeSession.rows[0]?.status, SessionStatus.Active);

    await runPreviewSeed(db);
    const userCount = await db.query<{ count: string }>(
      "SELECT COUNT(*)::text AS count FROM users",
    );
    assert.equal(userCount.rows[0]?.count, "6");
  });

  it("student B is not enrolled; student C stays Pending for OutOfRadius gates (AC-07, AC-08)", async () => {
    await resetDb(() => runPreviewSeed(db));

    const studentBEnrollment = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM enrollments
       WHERE student_id = $1 AND class_id = $2 AND subject_id = $3`,
      [PREVIEW_IDS.studentB, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
    );
    assert.equal(studentBEnrollment.rows[0]?.count, "0");

    const studentCAttendance = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records
       WHERE session_id = $1 AND student_id = $2`,
      [PREVIEW_IDS.sessionActive, PREVIEW_IDS.studentC],
    );
    assert.equal(studentCAttendance.rows[0]?.status, "Pending");
  });

  it("refreshes browser-gate QR fixtures on re-seed (FR-07, AC-09, AC-10)", async () => {
    await resetDb(() => runPreviewSeed(db));

    await db.query(
      `UPDATE qr_tokens SET status = $2, issued_at = NOW() - INTERVAL '2 minutes'
       WHERE id = $1`,
      [PREVIEW_IDS.validQrToken, QrTokenStatus.Expired],
    );

    await ensurePreviewTokenFixtures(db);

    const validToken = await db.query<{ status: string; issued_at: Date }>(
      "SELECT status, issued_at FROM qr_tokens WHERE id = $1",
      [PREVIEW_IDS.validQrToken],
    );
    assert.equal(validToken.rows[0]?.status, QrTokenStatus.Valid);
    assert.ok(
      Date.now() - validToken.rows[0]!.issued_at.getTime() < 5_000,
      "valid fixture issued_at should be refreshed",
    );

    const consumedToken = await db.query<{ status: string }>(
      "SELECT status FROM qr_tokens WHERE id = $1",
      [PREVIEW_IDS.consumedQrToken],
    );
    assert.equal(consumedToken.rows[0]?.status, QrTokenStatus.Consumed);
  });

  it("seeds monitor fixtures with spoof badge and token reuse alert (AC-10, FR-09, BR-11)", async () => {
    await resetDb(() => runPreviewSeed(db));

    const spoofAttempt = await db.query<{ outcome: string }>(
      "SELECT outcome FROM check_in_attempts WHERE id = $1",
      [PREVIEW_IDS.spoofCheckInAttempt],
    );
    assert.equal(spoofAttempt.rows[0]?.outcome, "SpoofSuspected");

    const reuseAlert = await db.query<{ event_type: string }>(
      "SELECT event_type FROM security_audit_logs WHERE id = $1",
      [PREVIEW_IDS.tokenReuseAlert],
    );
    assert.equal(reuseAlert.rows[0]?.event_type, "TokenReuseAlert");

    await ensurePreviewMonitorFixtures(db);
    const studentPresent = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records
       WHERE session_id = $1 AND student_id = $2`,
      [PREVIEW_IDS.sessionActive, PREVIEW_IDS.student],
    );
    assert.equal(studentPresent.rows[0]?.status, "Present");
  });

  it("idempotent re-seed restores reference data after roster truncate (AC-07, AC-08)", async () => {
    await resetDb(() => runPreviewSeed(db));
    await truncateRosterTables(db);

    await runPreviewSeed(db);

    const classRow = await db.query<{ code: string }>(
      "SELECT code FROM classes WHERE id = $1",
      [PREVIEW_IDS.classHesd01],
    );
    assert.equal(classRow.rows[0]?.code, "HESD-01");

    const studentCAttendance = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records
       WHERE session_id = $1 AND student_id = $2`,
      [PREVIEW_IDS.sessionActive, PREVIEW_IDS.studentC],
    );
    assert.equal(studentCAttendance.rows[0]?.status, "Pending");
  });

  it("ensurePreviewReferenceData opens Active session when fixtures truncated (FR-07)", async () => {
    await resetDb(() => runPreviewSeed(db));
    await truncateCheckInTables(db);
    await truncateRosterTables(db);

    await ensurePreviewReferenceData(db);
    await ensurePreviewTokenFixtures(db);
    await ensurePreviewMonitorFixtures(db);

    const activeSession = await db.query<{ status: string }>(
      "SELECT status FROM sessions WHERE id = $1",
      [PREVIEW_IDS.sessionActive],
    );
    assert.equal(activeSession.rows[0]?.status, SessionStatus.Active);
  });

  it("deactivated login returns AccountDeactivated (TC-NFR-17-013)", async () => {
    await resetDb(() => runPreviewSeed(db));

    const { AuthService } = await import("../modules/identity-auth/auth-service.js");
    const { UserRepository } = await import("../modules/identity-auth/user-repository.js");
    const { SessionStore } = await import("../auth/session-store.js");
    const auth = new AuthService(new UserRepository(db), new SessionStore(db));

    await assert.rejects(
      () =>
        auth.authenticate({
          email: PREVIEW_CREDENTIALS.deactivated.email,
          password: PREVIEW_CREDENTIALS.deactivated.password,
        }),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.errorCode, ErrorCode.AccountDeactivated);
        return true;
      },
    );
  });
});
