import {
  AttendanceStatus,
  QrTokenStatus,
  SessionStatus,
  UserRole,
  computeTokenExpiresAt,
} from "@wecheck/domain";
import type { DbPool } from "./db.js";
import { now } from "./clock.js";
import { runWhenPreviewDbIdle } from "./integration-test-lock.js";
import { hashPassword } from "../modules/identity-auth/password-hasher.js";
import { SessionService } from "../modules/session-management/session-service.js";

/** Deterministic preview fixture IDs — mirrored in apps/web preview-fixtures.ts */
export const PREVIEW_IDS = {
  admin: "00000000-0000-4000-8000-000000000001",
  instructor: "00000000-0000-4000-8000-000000000002",
  instructor2: "00000000-0000-4000-8000-000000000007",
  student: "00000000-0000-4000-8000-000000000003",
  deactivatedStudent: "00000000-0000-4000-8000-000000000004",
  studentB: "00000000-0000-4000-8000-000000000005",
  studentC: "00000000-0000-4000-8000-000000000006",
  classHesd01: "10000000-0000-4000-8000-000000000101",
  classHesd02: "10000000-0000-4000-8000-000000000102",
  subjectSwe101: "20000000-0000-4000-8000-000000000201",
  subjectSwe102: "20000000-0000-4000-8000-000000000202",
  sessionActive: "30000000-0000-4000-8000-000000000301",
  sessionDraft: "30000000-0000-4000-8000-000000000302",
  sessionClosed: "30000000-0000-4000-8000-000000000303",
  staleQrToken: "40000000-0000-4000-8000-000000000401",
  consumedQrToken: "40000000-0000-4000-8000-000000000402",
  validQrToken: "40000000-0000-4000-8000-000000000403",
  closedStaleQrToken: "40000000-0000-4000-8000-000000000404",
  spoofCheckInAttempt: "50000000-0000-4000-8000-000000000501",
  tokenReuseAlert: "50000000-0000-4000-8000-000000000502",
} as const;

/** Fixed QR token rows for browser gates — must stay out of scheduler mass-expire. */
export const PREVIEW_QR_TOKEN_FIXTURE_IDS = [
  PREVIEW_IDS.staleQrToken,
  PREVIEW_IDS.consumedQrToken,
  PREVIEW_IDS.validQrToken,
  PREVIEW_IDS.closedStaleQrToken,
] as const;

/** Vietnamese display names for browser NFR-17 gates — no English user-facing copy in headers. */
export const PREVIEW_DISPLAY_NAMES = {
  admin: "Quản trị viên Phòng đào tạo",
  instructor: "Giảng viên Nguyễn Văn B",
  instructor2: "Giảng viên Trần Thị C",
  student: "Sinh viên Nguyễn Văn A",
  deactivated: "Sinh viên Võ Văn D",
  studentB: "Sinh viên Trần Thị B",
  studentC: "Sinh viên Lê Văn C",
} as const;

export const PREVIEW_CREDENTIALS = {
  admin: { email: "admin@example.edu.vn", password: "AdminPass123" },
  instructor: { email: "instructor@example.edu.vn", password: "InstructorPass8" },
  instructor2: { email: "instructor2@example.edu.vn", password: "InstructorPass8" },
  student: { email: "student@example.edu.vn", password: "StudentPass8" },
  deactivated: { email: "deactivated@example.edu.vn", password: "StudentPass8" },
  studentB: { email: "studentb@example.edu.vn", password: "StudentPass8" },
  studentC: { email: "studentc@example.edu.vn", password: "StudentPass8" },
} as const;

const SEED_MARKER_KEY = "preview_seed_version";
const SEED_MARKER_VALUE = "1";

/** Verify browser-gate fixture rows — never trust policy_settings marker alone. */
async function isSeedApplied(db: DbPool): Promise<boolean> {
  const deactivated = await db.query<{ active: boolean }>(
    "SELECT active FROM users WHERE email = $1 AND id = $2",
    [PREVIEW_CREDENTIALS.deactivated.email, PREVIEW_IDS.deactivatedStudent],
  );
  if (deactivated.rows.length === 0 || deactivated.rows[0]?.active !== false) {
    return false;
  }

  const admin = await db.query<{ id: string; role: string }>(
    "SELECT id, role FROM users WHERE email = $1 AND active = true",
    [PREVIEW_CREDENTIALS.admin.email],
  );
  if (admin.rows.length === 0 || admin.rows[0]?.role !== UserRole.TrainingOfficeAdmin) {
    return false;
  }

  const instructor = await db.query<{ id: string }>(
    "SELECT id FROM users WHERE email = $1 AND active = true",
    [PREVIEW_CREDENTIALS.instructor.email],
  );
  if (instructor.rows.length === 0) return false;

  const student = await db.query<{ id: string }>(
    "SELECT id FROM users WHERE email = $1 AND active = true",
    [PREVIEW_CREDENTIALS.student.email],
  );
  if (student.rows.length === 0) return false;

  const studentB = await db.query<{ id: string }>(
    "SELECT id FROM users WHERE email = $1 LIMIT 1",
    [PREVIEW_CREDENTIALS.studentB.email],
  );
  if (studentB.rows.length === 0) return false;

  const staleToken = await db.query<{ status: string }>(
    "SELECT status FROM qr_tokens WHERE id = $1",
    [PREVIEW_IDS.staleQrToken],
  );
  if (staleToken.rows[0]?.status !== QrTokenStatus.Expired) return false;

  const activeSession = await db.query<{ status: string }>(
    "SELECT status FROM sessions WHERE id = $1",
    [PREVIEW_IDS.sessionActive],
  );
  if (activeSession.rows[0]?.status !== SessionStatus.Active) return false;

  const historyCount = await db.query<{ count: string }>(
    `SELECT COUNT(*)::text AS count FROM attendance_records ar
     INNER JOIN sessions s ON s.id = ar.session_id
     WHERE ar.student_id = $1 AND s.status = $2`,
    [PREVIEW_IDS.student, SessionStatus.Closed],
  );
  return Number(historyCount.rows[0]?.count ?? "0") >= PREVIEW_HISTORY_MIN_COUNT;
}

const PREVIEW_USER_IDS = [
  PREVIEW_IDS.admin,
  PREVIEW_IDS.instructor,
  PREVIEW_IDS.instructor2,
  PREVIEW_IDS.student,
  PREVIEW_IDS.deactivatedStudent,
  PREVIEW_IDS.studentB,
  PREVIEW_IDS.studentC,
] as const;

const PREVIEW_INSTITUTIONAL_IDS = [
  "ADMIN001",
  "GV2026001",
  "GV2026002",
  "SV2026001",
  "SV2026099",
  "SV2026002",
  "SV2026003",
] as const;

/** Remove integration-test leftovers that block preview fixture upserts. */
async function clearPreviewUserConflicts(db: DbPool): Promise<void> {
  const previewEmails = Object.values(PREVIEW_CREDENTIALS).map((c) => c.email);
  await db.query(
    `DELETE FROM users
     WHERE (email = ANY($1::text[]) OR institutional_id = ANY($2::text[]))
       AND id <> ALL($3::uuid[])`,
    [previewEmails, PREVIEW_INSTITUTIONAL_IDS, PREVIEW_USER_IDS],
  );
}

const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;

/** Upsert reference rows required by token/monitor fixtures after partial DB resets. */
export async function ensurePreviewReferenceData(db: DbPool): Promise<void> {
  const scheduledStart = new Date(now().getTime() + 60 * 60 * 1000);

  await db.query(
    `INSERT INTO classes (id, code, name) VALUES
       ($1, 'HESD-01', 'HESD Cohort A'),
       ($2, 'HESD-02', 'HESD Cohort B')
     ON CONFLICT (id) DO NOTHING`,
    [PREVIEW_IDS.classHesd01, PREVIEW_IDS.classHesd02],
  );

  await db.query(
    `INSERT INTO subjects (id, code, name) VALUES
       ($1, 'SWE-101', 'Software Engineering 101'),
       ($2, 'SWE-102', 'Software Engineering 102')
     ON CONFLICT (id) DO NOTHING`,
    [PREVIEW_IDS.subjectSwe101, PREVIEW_IDS.subjectSwe102],
  );

  await db.query(
    `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (instructor_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.instructor, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
  );

  await db.query(
    `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (instructor_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.instructor2, PREVIEW_IDS.classHesd02, PREVIEW_IDS.subjectSwe102],
  );

  await db.query(
    `INSERT INTO enrollments (student_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (student_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.student, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
  );

  await db.query(
    `INSERT INTO sessions (
       id, instructor_id, class_id, subject_id, title, room_name,
       room_latitude, room_longitude, gps_radius_meters, scheduled_start,
       status, version
     ) VALUES
       ($1, $2, $3, $4, $5, $6, $7, $8, 100, $9, $10, 1),
       ($11, $12, $13, $14, $15, $16, $17, $18, 100, $19, $20, 1)
     ON CONFLICT (id) DO NOTHING`,
    [
      PREVIEW_IDS.sessionDraft,
      PREVIEW_IDS.instructor,
      PREVIEW_IDS.classHesd02,
      PREVIEW_IDS.subjectSwe101,
      "DB-201 — Buổi 3",
      "Phòng B102",
      ROOM_LAT,
      ROOM_LNG,
      scheduledStart,
      SessionStatus.Draft,
      PREVIEW_IDS.sessionActive,
      PREVIEW_IDS.instructor,
      PREVIEW_IDS.classHesd01,
      PREVIEW_IDS.subjectSwe101,
      "SWE-101 — Buổi 5",
      "Phòng A201",
      ROOM_LAT,
      ROOM_LNG,
      scheduledStart,
      SessionStatus.Draft,
    ],
  );

  const activeSession = await db.query<{ status: string }>(
    "SELECT status FROM sessions WHERE id = $1",
    [PREVIEW_IDS.sessionActive],
  );
  if (activeSession.rows[0]?.status === SessionStatus.Draft) {
    const sessionService = new SessionService(db);
    await sessionService.open(
      PREVIEW_IDS.sessionActive,
      PREVIEW_IDS.instructor,
      UserRole.Instructor,
    );
    sessionService.qr.stopAll();
  }

  const closedAt = now();
  const openedAt = new Date(closedAt.getTime() - 2 * 60 * 60 * 1000);
  await db.query(
    `INSERT INTO sessions (
       id, instructor_id, class_id, subject_id, title, room_name,
       room_latitude, room_longitude, gps_radius_meters, scheduled_start,
       status, opened_at, closed_at, version
     ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 100, $9, $10, $11, $12, 1)
     ON CONFLICT (id) DO NOTHING`,
    [
      PREVIEW_IDS.sessionClosed,
      PREVIEW_IDS.instructor,
      PREVIEW_IDS.classHesd01,
      PREVIEW_IDS.subjectSwe101,
      "NET-301 — Buổi 1",
      "Phòng C301",
      ROOM_LAT,
      ROOM_LNG,
      scheduledStart,
      SessionStatus.Closed,
      openedAt,
      closedAt,
    ],
  );
}

/** Upsert monitor dashboard fixtures: spoof row + token-reuse alert (AC-10, FR-09, BR-11). */
export async function ensurePreviewMonitorFixtures(db: DbPool): Promise<void> {
  await ensurePreviewTokenFixtures(db);

  const studentCHash = await hashPassword(PREVIEW_CREDENTIALS.studentC.password);
  await db.query(
    `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
     VALUES ($1, 'SV2026003', $5, $2, $3, $4, true)
     ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name`,
    [
      PREVIEW_IDS.studentC,
      PREVIEW_CREDENTIALS.studentC.email,
      studentCHash,
      UserRole.Student,
      PREVIEW_DISPLAY_NAMES.studentC,
    ],
  );

  await db.query(
    `INSERT INTO enrollments (student_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (student_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.studentC, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
  );

  await db.query(
    `INSERT INTO attendance_records (id, session_id, student_id, status)
     SELECT gen_random_uuid(), $1, $2, 'Pending'
     WHERE NOT EXISTS (
       SELECT 1 FROM attendance_records WHERE session_id = $1 AND student_id = $2
     )`,
    [PREVIEW_IDS.sessionActive, PREVIEW_IDS.studentC],
  );

  await db.query(
    `UPDATE attendance_records
     SET status = 'Pending', checked_in_at = NULL, updated_at = NOW()
     WHERE session_id = $1 AND student_id IN ($2, $3)`,
    [PREVIEW_IDS.sessionActive, PREVIEW_IDS.studentC, PREVIEW_IDS.student],
  );

  await ensurePreviewTokenFixtures(db);

  await db.query(
    `INSERT INTO check_in_attempts (
       id, session_id, student_id, qr_token_id, outcome, attempted_at, spoof_flags
     ) VALUES ($1, $2, $3, $4, 'SpoofSuspected', NOW(), $5::jsonb)
     ON CONFLICT (id) DO UPDATE SET
       outcome = EXCLUDED.outcome,
       attempted_at = EXCLUDED.attempted_at,
       spoof_flags = EXCLUDED.spoof_flags`,
    [
      PREVIEW_IDS.spoofCheckInAttempt,
      PREVIEW_IDS.sessionActive,
      PREVIEW_IDS.studentC,
      PREVIEW_IDS.validQrToken,
      JSON.stringify({ mockLocationDetected: true }),
    ],
  );

  await db.query(
    `INSERT INTO security_audit_logs (
       id, event_type, session_id, qr_token_id, student_id, details, created_at
     ) VALUES ($1, 'TokenReuseAlert', $2, $3, $4, $5::jsonb, NOW())
     ON CONFLICT (id) DO UPDATE SET created_at = NOW()`,
    [
      PREVIEW_IDS.tokenReuseAlert,
      PREVIEW_IDS.sessionActive,
      PREVIEW_IDS.consumedQrToken,
      PREVIEW_IDS.studentC,
      JSON.stringify({ consumedByStudentId: PREVIEW_IDS.student }),
    ],
  );
}

/** Upsert browser-gate QR token fixtures without re-opening sessions. */
export async function ensurePreviewTokenFixtures(db: DbPool): Promise<void> {
  const current = now();
  const staleIssued = new Date(current.getTime() - 60 * 60 * 1000);
  const staleExpires = computeTokenExpiresAt(staleIssued);
  await db.query(
    `INSERT INTO qr_tokens (id, session_id, status, issued_at, expires_at)
     VALUES ($1, $2, $3, $4, $5)
     ON CONFLICT (id) DO UPDATE SET
       status = EXCLUDED.status,
       issued_at = EXCLUDED.issued_at,
       expires_at = EXCLUDED.expires_at,
       consumed_at = NULL,
       consumed_by_student_id = NULL`,
    [
      PREVIEW_IDS.staleQrToken,
      PREVIEW_IDS.sessionActive,
      QrTokenStatus.Expired,
      staleIssued,
      staleExpires,
    ],
  );

  const consumedIssued = current;
  const consumedExpires = computeTokenExpiresAt(consumedIssued);
  await db.query(
    `INSERT INTO qr_tokens (
       id, session_id, status, issued_at, expires_at, consumed_at, consumed_by_student_id
     ) VALUES ($1, $2, $3, $4, $5, $6, $7)
     ON CONFLICT (id) DO UPDATE SET
       status = EXCLUDED.status,
       issued_at = EXCLUDED.issued_at,
       expires_at = EXCLUDED.expires_at,
       consumed_at = EXCLUDED.consumed_at,
       consumed_by_student_id = EXCLUDED.consumed_by_student_id`,
    [
      PREVIEW_IDS.consumedQrToken,
      PREVIEW_IDS.sessionActive,
      QrTokenStatus.Consumed,
      consumedIssued,
      consumedExpires,
      consumedIssued,
      PREVIEW_IDS.student,
    ],
  );

  const validIssued = current;
  const validExpires = computeTokenExpiresAt(validIssued);
  await db.query(
    `INSERT INTO qr_tokens (id, session_id, status, issued_at, expires_at)
     VALUES ($1, $2, $3, $4, $5)
     ON CONFLICT (id) DO UPDATE SET
       status = EXCLUDED.status,
       issued_at = EXCLUDED.issued_at,
       expires_at = EXCLUDED.expires_at,
       consumed_at = NULL,
       consumed_by_student_id = NULL`,
    [
      PREVIEW_IDS.validQrToken,
      PREVIEW_IDS.sessionActive,
      QrTokenStatus.Valid,
      validIssued,
      validExpires,
    ],
  );

  const closedStaleIssued = new Date(current.getTime() - 60 * 60 * 1000);
  const closedStaleExpires = computeTokenExpiresAt(closedStaleIssued);
  await db.query(
    `INSERT INTO qr_tokens (id, session_id, status, issued_at, expires_at)
     VALUES ($1, $2, $3, $4, $5)
     ON CONFLICT (id) DO UPDATE SET
       status = EXCLUDED.status,
       issued_at = EXCLUDED.issued_at,
       expires_at = EXCLUDED.expires_at,
       consumed_at = NULL,
       consumed_by_student_id = NULL`,
    [
      PREVIEW_IDS.closedStaleQrToken,
      PREVIEW_IDS.sessionClosed,
      QrTokenStatus.Expired,
      closedStaleIssued,
      closedStaleExpires,
    ],
  );
}

/** Restore unassigned instructor B for report RBAC browser gates (AC-12, BR-08). */
export async function ensurePreviewInstructor2Fixtures(db: DbPool): Promise<void> {
  const instructor2Hash = await hashPassword(PREVIEW_CREDENTIALS.instructor2.password);
  await db.query(
    `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
     VALUES ($1, 'GV2026002', $2, $3, $4, $5, true)
     ON CONFLICT (id) DO UPDATE SET
       institutional_id = EXCLUDED.institutional_id,
       display_name = EXCLUDED.display_name,
       email = EXCLUDED.email,
       password_hash = EXCLUDED.password_hash,
       role = EXCLUDED.role,
       active = EXCLUDED.active`,
    [
      PREVIEW_IDS.instructor2,
      PREVIEW_DISPLAY_NAMES.instructor2,
      PREVIEW_CREDENTIALS.instructor2.email,
      instructor2Hash,
      UserRole.Instructor,
    ],
  );

  await db.query(
    `DELETE FROM class_assignments
     WHERE instructor_id = $1 AND (class_id <> $2 OR subject_id <> $3)`,
    [PREVIEW_IDS.instructor2, PREVIEW_IDS.classHesd02, PREVIEW_IDS.subjectSwe102],
  );

  await db.query(
    `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (instructor_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.instructor2, PREVIEW_IDS.classHesd02, PREVIEW_IDS.subjectSwe102],
  );
}

/** Restore primary login accounts after partial DB resets (FR-02, TC-FR-02-021). */
export async function ensurePreviewCoreAuthFixtures(db: DbPool): Promise<void> {
  await clearPreviewUserConflicts(db);

  const adminHash = await hashPassword(PREVIEW_CREDENTIALS.admin.password);
  const instructorHash = await hashPassword(PREVIEW_CREDENTIALS.instructor.password);
  const studentHash = await hashPassword(PREVIEW_CREDENTIALS.student.password);

  await db.query(
    `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
     VALUES
       ($1, 'ADMIN001', $4, $2, $3, $5, true),
       ($6, 'GV2026001', $9, $7, $8, $10, true),
       ($11, 'SV2026001', $14, $12, $13, $15, true)
     ON CONFLICT (id) DO UPDATE SET
       institutional_id = EXCLUDED.institutional_id,
       display_name = EXCLUDED.display_name,
       email = EXCLUDED.email,
       password_hash = EXCLUDED.password_hash,
       role = EXCLUDED.role,
       active = EXCLUDED.active`,
    [
      PREVIEW_IDS.admin,
      PREVIEW_CREDENTIALS.admin.email,
      adminHash,
      PREVIEW_DISPLAY_NAMES.admin,
      UserRole.TrainingOfficeAdmin,
      PREVIEW_IDS.instructor,
      PREVIEW_CREDENTIALS.instructor.email,
      instructorHash,
      PREVIEW_DISPLAY_NAMES.instructor,
      UserRole.Instructor,
      PREVIEW_IDS.student,
      PREVIEW_CREDENTIALS.student.email,
      studentHash,
      PREVIEW_DISPLAY_NAMES.student,
      UserRole.Student,
    ],
  );
}

/** Restore only the deactivated browser-gate user without re-upserting all preview accounts. */
export async function ensurePreviewDeactivatedUser(db: DbPool): Promise<void> {
  const existing = await db.query<{ active: boolean }>(
    "SELECT active FROM users WHERE id = $1",
    [PREVIEW_IDS.deactivatedStudent],
  );
  if (existing.rows[0]?.active === false) return;

  const deactivatedHash = await hashPassword(PREVIEW_CREDENTIALS.deactivated.password);
  await db.query(
    `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
     VALUES ($1, 'SV2026099', $5, $2, $3, $4, false)
     ON CONFLICT (id) DO UPDATE SET
       institutional_id = EXCLUDED.institutional_id,
       display_name = EXCLUDED.display_name,
       email = EXCLUDED.email,
       password_hash = EXCLUDED.password_hash,
       role = EXCLUDED.role,
       active = EXCLUDED.active`,
    [
      PREVIEW_IDS.deactivatedStudent,
      PREVIEW_CREDENTIALS.deactivated.email,
      deactivatedHash,
      UserRole.Student,
      PREVIEW_DISPLAY_NAMES.deactivated,
    ],
  );
}
/** Upsert all preview users — used on initial seed only (avoids integration-test races). */
export async function ensurePreviewUserFixtures(db: DbPool): Promise<void> {
  await clearPreviewUserConflicts(db);

  const adminHash = await hashPassword(PREVIEW_CREDENTIALS.admin.password);
  const instructorHash = await hashPassword(PREVIEW_CREDENTIALS.instructor.password);
  const instructor2Hash = await hashPassword(PREVIEW_CREDENTIALS.instructor2.password);
  const studentHash = await hashPassword(PREVIEW_CREDENTIALS.student.password);
  const deactivatedHash = await hashPassword(PREVIEW_CREDENTIALS.deactivated.password);
  const studentBHash = await hashPassword(PREVIEW_CREDENTIALS.studentB.password);
  const studentCHash = await hashPassword(PREVIEW_CREDENTIALS.studentC.password);

  await db.query(
    `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
     VALUES
       ($1, 'ADMIN001', $25, $2, $3, $4, true),
       ($5, 'GV2026001', $26, $6, $7, $8, true),
       ($31, 'GV2026002', $32, $33, $34, $8, true),
       ($9, 'SV2026001', $27, $10, $11, $12, true),
       ($13, 'SV2026099', $28, $14, $15, $16, false),
       ($17, 'SV2026002', $29, $18, $19, $20, true),
       ($21, 'SV2026003', $30, $22, $23, $24, true)
     ON CONFLICT (id) DO UPDATE SET
       institutional_id = EXCLUDED.institutional_id,
       display_name = EXCLUDED.display_name,
       email = EXCLUDED.email,
       password_hash = EXCLUDED.password_hash,
       role = EXCLUDED.role,
       active = EXCLUDED.active`,
    [
      PREVIEW_IDS.admin,
      PREVIEW_CREDENTIALS.admin.email,
      adminHash,
      UserRole.TrainingOfficeAdmin,
      PREVIEW_IDS.instructor,
      PREVIEW_CREDENTIALS.instructor.email,
      instructorHash,
      UserRole.Instructor,
      PREVIEW_IDS.student,
      PREVIEW_CREDENTIALS.student.email,
      studentHash,
      UserRole.Student,
      PREVIEW_IDS.deactivatedStudent,
      PREVIEW_CREDENTIALS.deactivated.email,
      deactivatedHash,
      UserRole.Student,
      PREVIEW_IDS.studentB,
      PREVIEW_CREDENTIALS.studentB.email,
      studentBHash,
      UserRole.Student,
      PREVIEW_IDS.studentC,
      PREVIEW_CREDENTIALS.studentC.email,
      studentCHash,
      UserRole.Student,
      PREVIEW_DISPLAY_NAMES.admin,
      PREVIEW_DISPLAY_NAMES.instructor,
      PREVIEW_DISPLAY_NAMES.student,
      PREVIEW_DISPLAY_NAMES.deactivated,
      PREVIEW_DISPLAY_NAMES.studentB,
      PREVIEW_DISPLAY_NAMES.studentC,
      PREVIEW_IDS.instructor2,
      PREVIEW_DISPLAY_NAMES.instructor2,
      PREVIEW_CREDENTIALS.instructor2.email,
      instructor2Hash,
    ],
  );
}

/** Closed-session count for /history pagination browser gates (TC-AC-14-008). */
const PREVIEW_HISTORY_SESSION_COUNT = 30;

/** Minimum closed history rows before preview refresh skips history upsert. */
const PREVIEW_HISTORY_MIN_COUNT = 25;

const PREVIEW_HISTORY_STATUSES = [
  AttendanceStatus.Present,
  AttendanceStatus.Absent,
  AttendanceStatus.Excused,
] as const;

function previewHistorySessionId(index: number): string {
  return `31000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
}

/** Upsert closed-session attendance for student history browser gates (AC-14, FR-14). */
export async function ensurePreviewHistoryFixtures(db: DbPool): Promise<void> {
  await ensurePreviewReferenceData(db);

  await db.query(
    `INSERT INTO enrollments (student_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (student_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.student, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe102],
  );

  const baseMs = now().getTime();

  for (let i = 0; i < PREVIEW_HISTORY_SESSION_COUNT; i++) {
    const sessionId =
      i === 0 ? PREVIEW_IDS.sessionClosed : previewHistorySessionId(i);
    const daysAgo = i + 1;
    const scheduledStart = new Date(baseMs - daysAgo * 24 * 60 * 60 * 1000);
    const openedAt = scheduledStart;
    const closedAt = new Date(scheduledStart.getTime() + 2 * 60 * 60 * 1000);
    const subjectId =
      i % 2 === 0 ? PREVIEW_IDS.subjectSwe101 : PREVIEW_IDS.subjectSwe102;
    const status = PREVIEW_HISTORY_STATUSES[i % PREVIEW_HISTORY_STATUSES.length]!;
    const checkedInAt =
      status === AttendanceStatus.Present
        ? new Date(scheduledStart.getTime() + 15 * 60 * 1000)
        : null;

    await db.query(
      `INSERT INTO sessions (
         id, instructor_id, class_id, subject_id, title, room_name,
         room_latitude, room_longitude, gps_radius_meters, scheduled_start,
         status, opened_at, closed_at, version
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 100, $9, $10, $11, $12, 1)
       ON CONFLICT (id) DO UPDATE SET
         status = EXCLUDED.status,
         subject_id = EXCLUDED.subject_id,
         scheduled_start = EXCLUDED.scheduled_start,
         opened_at = EXCLUDED.opened_at,
         closed_at = EXCLUDED.closed_at,
         updated_at = NOW()`,
      [
        sessionId,
        PREVIEW_IDS.instructor,
        PREVIEW_IDS.classHesd01,
        subjectId,
        `SWE — Buổi lịch sử ${i + 1}`,
        `Phòng H${String(i + 1).padStart(3, "0")}`,
        ROOM_LAT,
        ROOM_LNG,
        scheduledStart,
        SessionStatus.Closed,
        openedAt,
        closedAt,
      ],
    );

    await db.query(
      `INSERT INTO attendance_records (id, session_id, student_id, status, checked_in_at)
       VALUES (gen_random_uuid(), $1, $2, $3, $4)
       ON CONFLICT (session_id, student_id) DO UPDATE SET
         status = EXCLUDED.status,
         checked_in_at = EXCLUDED.checked_in_at,
         updated_at = NOW()`,
      [sessionId, PREVIEW_IDS.student, status, checkedInAt],
    );
  }
}

/** Upsert non-enrolled student B for NotEnrolled / TokenAlreadyUsed browser gates. */
async function ensurePreviewStudentFixtures(db: DbPool): Promise<void> {
  const studentBHash = await hashPassword(PREVIEW_CREDENTIALS.studentB.password);
  await db.query(
    `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
     VALUES ($1, 'SV2026002', $5, $2, $3, $4, true)
     ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name`,
    [
      PREVIEW_IDS.studentB,
      PREVIEW_CREDENTIALS.studentB.email,
      studentBHash,
      UserRole.Student,
      PREVIEW_DISPLAY_NAMES.studentB,
    ],
  );

  await db.query(
    `DELETE FROM enrollments
     WHERE student_id = $1 AND class_id = $2 AND subject_id = $3`,
    [PREVIEW_IDS.studentB, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
  );
}

/** Restore Vietnamese display names after partial DB resets (NFR-17). */
async function ensurePreviewDisplayNames(db: DbPool): Promise<void> {
  const rows: Array<[string, string]> = [
    [PREVIEW_IDS.admin, PREVIEW_DISPLAY_NAMES.admin],
    [PREVIEW_IDS.instructor, PREVIEW_DISPLAY_NAMES.instructor],
    [PREVIEW_IDS.instructor2, PREVIEW_DISPLAY_NAMES.instructor2],
    [PREVIEW_IDS.student, PREVIEW_DISPLAY_NAMES.student],
    [PREVIEW_IDS.deactivatedStudent, PREVIEW_DISPLAY_NAMES.deactivated],
    [PREVIEW_IDS.studentB, PREVIEW_DISPLAY_NAMES.studentB],
    [PREVIEW_IDS.studentC, PREVIEW_DISPLAY_NAMES.studentC],
  ];
  for (const [id, displayName] of rows) {
    await db.query("UPDATE users SET display_name = $2, updated_at = NOW() WHERE id = $1", [
      id,
      displayName,
    ]);
  }
}

async function markSeedApplied(db: DbPool): Promise<void> {
  await db.query(
    `INSERT INTO policy_settings (key, value)
     VALUES ($1, $2)
     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()`,
    [SEED_MARKER_KEY, SEED_MARKER_VALUE],
  );
}

/** Resume QR rotation for Active preview sessions after API startup. */
export async function resumePreviewQrSchedulers(
  db: DbPool,
  qr: SessionService["qr"],
): Promise<void> {
  qr.setProtectedTokenIds(PREVIEW_QR_TOKEN_FIXTURE_IDS);
  await ensurePreviewReferenceData(db);
  await ensurePreviewTokenFixtures(db);
  await ensurePreviewMonitorFixtures(db);
  const result = await db.query<{ id: string }>(
    "SELECT id FROM sessions WHERE status = $1",
    [SessionStatus.Active],
  );
  for (const row of result.rows) {
    qr.start(row.id);
  }
}

const PREVIEW_TOKEN_REFRESH_MS = 20_000;

/** Lightweight refresh after integration truncates sessions — history before QR tokens (FK order). */
export async function refreshPreviewBrowserFixtures(db: DbPool): Promise<void> {
  await ensurePreviewCoreAuthFixtures(db);
  await ensurePreviewDeactivatedUser(db);
  await ensurePreviewInstructor2Fixtures(db);
  await ensurePreviewDisplayNames(db);
  await ensurePreviewReferenceData(db);

  const historyCount = await db.query<{ count: string }>(
    `SELECT COUNT(*)::text AS count FROM attendance_records ar
     INNER JOIN sessions s ON s.id = ar.session_id
     WHERE ar.student_id = $1 AND s.status = $2`,
    [PREVIEW_IDS.student, SessionStatus.Closed],
  );
  if (Number(historyCount.rows[0]?.count ?? "0") < PREVIEW_HISTORY_MIN_COUNT) {
    await ensurePreviewHistoryFixtures(db);
  }

  await ensurePreviewTokenFixtures(db);
}

/** Keep browser-gate QR fixtures within 30 s TTL while preview stack runs. */
export function startPreviewTokenRefresh(db: DbPool): () => void {
  const handle = setInterval(() => {
    void runWhenPreviewDbIdle(db, () => refreshPreviewBrowserFixtures(db)).catch(
      (error: unknown) => {
        console.error("Preview token fixture refresh failed:", error);
      },
    );
  }, PREVIEW_TOKEN_REFRESH_MS);
  handle.unref();
  return () => clearInterval(handle);
}

/** Idempotent preview fixtures for browser gates (NFR-17, NFR-06). */
export async function runPreviewSeed(db: DbPool): Promise<void> {
  if (await isSeedApplied(db)) {
    await runWhenPreviewDbIdle(db, () => refreshPreviewBrowserFixtures(db));
    return;
  }

  await ensurePreviewUserFixtures(db);

  await db.query(
    `INSERT INTO classes (id, code, name) VALUES
       ($1, 'HESD-01', 'HESD Cohort A'),
       ($2, 'HESD-02', 'HESD Cohort B')
     ON CONFLICT (id) DO NOTHING`,
    [PREVIEW_IDS.classHesd01, PREVIEW_IDS.classHesd02],
  );

  await db.query(
    `INSERT INTO subjects (id, code, name) VALUES
       ($1, 'SWE-101', 'Software Engineering 101'),
       ($2, 'SWE-102', 'Software Engineering 102')
     ON CONFLICT (id) DO NOTHING`,
    [PREVIEW_IDS.subjectSwe101, PREVIEW_IDS.subjectSwe102],
  );

  await db.query(
    `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (instructor_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.instructor, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
  );

  await db.query(
    `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (instructor_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.instructor2, PREVIEW_IDS.classHesd02, PREVIEW_IDS.subjectSwe102],
  );

  await db.query(
    `INSERT INTO enrollments (student_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (student_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.student, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
  );

  await db.query(
    `INSERT INTO enrollments (student_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (student_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.studentC, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
  );

  const sessionService = new SessionService(db);
  const scheduledStart = new Date(now().getTime() + 60 * 60 * 1000);

  await db.query(
    `INSERT INTO sessions (
       id, instructor_id, class_id, subject_id, title, room_name,
       room_latitude, room_longitude, gps_radius_meters, scheduled_start,
       status, version
     ) VALUES
       ($1, $2, $3, $4, $5, $6, $7, $8, 100, $9, $10, 1),
       ($11, $12, $13, $14, $15, $16, $17, $18, 100, $19, $20, 1)
     ON CONFLICT (id) DO NOTHING`,
    [
      PREVIEW_IDS.sessionDraft,
      PREVIEW_IDS.instructor,
      PREVIEW_IDS.classHesd02,
      PREVIEW_IDS.subjectSwe101,
      "DB-201 — Buổi 3",
      "Phòng B102",
      ROOM_LAT,
      ROOM_LNG,
      scheduledStart,
      SessionStatus.Draft,
      PREVIEW_IDS.sessionActive,
      PREVIEW_IDS.instructor,
      PREVIEW_IDS.classHesd01,
      PREVIEW_IDS.subjectSwe101,
      "SWE-101 — Buổi 5",
      "Phòng A201",
      ROOM_LAT,
      ROOM_LNG,
      scheduledStart,
      SessionStatus.Draft,
    ],
  );

  const activeSession = await db.query<{ status: string }>(
    "SELECT status FROM sessions WHERE id = $1",
    [PREVIEW_IDS.sessionActive],
  );
  if (activeSession.rows[0]?.status === SessionStatus.Draft) {
    await sessionService.open(
      PREVIEW_IDS.sessionActive,
      PREVIEW_IDS.instructor,
      UserRole.Instructor,
    );
  }

  const closedAt = now();
  const openedAt = new Date(closedAt.getTime() - 2 * 60 * 60 * 1000);
  await db.query(
    `INSERT INTO sessions (
       id, instructor_id, class_id, subject_id, title, room_name,
       room_latitude, room_longitude, gps_radius_meters, scheduled_start,
       status, opened_at, closed_at, version
     ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 100, $9, $10, $11, $12, 1)
     ON CONFLICT (id) DO NOTHING`,
    [
      PREVIEW_IDS.sessionClosed,
      PREVIEW_IDS.instructor,
      PREVIEW_IDS.classHesd01,
      PREVIEW_IDS.subjectSwe101,
      "NET-301 — Buổi 1",
      "Phòng C301",
      ROOM_LAT,
      ROOM_LNG,
      scheduledStart,
      SessionStatus.Closed,
      openedAt,
      closedAt,
    ],
  );

  await ensurePreviewTokenFixtures(db);
  await ensurePreviewStudentFixtures(db);
  await ensurePreviewInstructor2Fixtures(db);
  await ensurePreviewMonitorFixtures(db);
  await ensurePreviewHistoryFixtures(db);

  sessionService.qr.stopAll();
  await markSeedApplied(db);
}
