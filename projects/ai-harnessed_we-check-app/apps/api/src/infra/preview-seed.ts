import { QrTokenStatus, SessionStatus, UserRole } from "@wecheck/domain";
import type { DbPool } from "./db.js";
import { now } from "./clock.js";
import { hashPassword } from "../modules/identity-auth/password-hasher.js";
import { SessionService } from "../modules/session-management/session-service.js";

/** Deterministic preview fixture IDs — mirrored in apps/web preview-fixtures.ts */
export const PREVIEW_IDS = {
  admin: "00000000-0000-4000-8000-000000000001",
  instructor: "00000000-0000-4000-8000-000000000002",
  student: "00000000-0000-4000-8000-000000000003",
  deactivatedStudent: "00000000-0000-4000-8000-000000000004",
  classHesd01: "10000000-0000-4000-8000-000000000101",
  classHesd02: "10000000-0000-4000-8000-000000000102",
  subjectSwe101: "20000000-0000-4000-8000-000000000201",
  sessionActive: "30000000-0000-4000-8000-000000000301",
  sessionDraft: "30000000-0000-4000-8000-000000000302",
  sessionClosed: "30000000-0000-4000-8000-000000000303",
  staleQrToken: "40000000-0000-4000-8000-000000000401",
} as const;

export const PREVIEW_CREDENTIALS = {
  admin: { email: "admin@example.edu.vn", password: "AdminPass123" },
  instructor: { email: "instructor@example.edu.vn", password: "InstructorPass8" },
  student: { email: "student@example.edu.vn", password: "StudentPass8" },
  deactivated: { email: "deactivated@example.edu.vn", password: "StudentPass8" },
} as const;

const SEED_MARKER_KEY = "preview_seed_version";
const SEED_MARKER_VALUE = "1";

const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;

async function isSeedApplied(db: DbPool): Promise<boolean> {
  const result = await db.query<{ email: string }>(
    "SELECT email FROM users WHERE email = $1 LIMIT 1",
    [PREVIEW_CREDENTIALS.deactivated.email],
  );
  return result.rows.length > 0;
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
  const result = await db.query<{ id: string }>(
    "SELECT id FROM sessions WHERE status = $1",
    [SessionStatus.Active],
  );
  for (const row of result.rows) {
    qr.start(row.id);
  }
}

/** Idempotent preview fixtures for browser gates (NFR-17, NFR-06). */
export async function runPreviewSeed(db: DbPool): Promise<void> {
  if (await isSeedApplied(db)) {
    return;
  }

  const adminHash = await hashPassword(PREVIEW_CREDENTIALS.admin.password);
  const instructorHash = await hashPassword(PREVIEW_CREDENTIALS.instructor.password);
  const studentHash = await hashPassword(PREVIEW_CREDENTIALS.student.password);
  const deactivatedHash = await hashPassword(PREVIEW_CREDENTIALS.deactivated.password);

  await db.query(
    `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
     VALUES
       ($1, 'ADMIN001', 'Admin User', $2, $3, $4, true),
       ($5, 'GV2026001', 'Instructor One', $6, $7, $8, true),
       ($9, 'SV2026001', 'Student One', $10, $11, $12, true),
       ($13, 'SV2026099', 'Deactivated Student', $14, $15, $16, false)
     ON CONFLICT (id) DO NOTHING`,
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
    ],
  );

  await db.query(
    `INSERT INTO classes (id, code, name) VALUES
       ($1, 'HESD-01', 'HESD Cohort A'),
       ($2, 'HESD-02', 'HESD Cohort B')
     ON CONFLICT (id) DO NOTHING`,
    [PREVIEW_IDS.classHesd01, PREVIEW_IDS.classHesd02],
  );

  await db.query(
    `INSERT INTO subjects (id, code, name) VALUES ($1, 'SWE-101', 'Software Engineering 101')
     ON CONFLICT (id) DO NOTHING`,
    [PREVIEW_IDS.subjectSwe101],
  );

  await db.query(
    `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (instructor_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.instructor, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
  );

  await db.query(
    `INSERT INTO enrollments (student_id, class_id, subject_id)
     VALUES ($1, $2, $3)
     ON CONFLICT (student_id, class_id, subject_id) DO NOTHING`,
    [PREVIEW_IDS.student, PREVIEW_IDS.classHesd01, PREVIEW_IDS.subjectSwe101],
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

  await sessionService.open(
    PREVIEW_IDS.sessionActive,
    PREVIEW_IDS.instructor,
    UserRole.Instructor,
  );

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

  const staleIssued = new Date(now().getTime() - 60 * 60 * 1000);
  const staleExpires = new Date(staleIssued.getTime() + 30_000);
  await db.query(
    `INSERT INTO qr_tokens (id, session_id, status, issued_at, expires_at)
     VALUES ($1, $2, $3, $4, $5)
     ON CONFLICT (id) DO NOTHING`,
    [
      PREVIEW_IDS.staleQrToken,
      PREVIEW_IDS.sessionActive,
      QrTokenStatus.Expired,
      staleIssued,
      staleExpires,
    ],
  );

  sessionService.qr.stopAll();
  await markSeedApplied(db);
}
