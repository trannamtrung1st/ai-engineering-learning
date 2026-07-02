import { randomUUID } from "node:crypto";
import {
  QR_TOKEN_TTL_MS,
  SESSION_COOKIE_NAME,
  UserRole,
} from "@wecheck/domain";
import type { FastifyInstance } from "fastify";
import { createTestUser, SessionStore, truncateAuthTables } from "../../../../apps/api/src/auth/session-store.js";
import { hashPassword } from "../../../../apps/api/src/modules/identity-auth/password-hasher.js";
import { truncateCheckInTables } from "../../../../apps/api/src/modules/checkin-qr/check-in-service.js";
import {
  truncateNotificationTables,
  POLICY_KEY_ABSENCE_THRESHOLD,
} from "../../../../apps/api/src/modules/notifications/repositories.js";
import { NotificationService } from "../../../../apps/api/src/modules/notifications/notification-service.js";
import { truncateRosterTables } from "../../../../apps/api/src/modules/roster-enrollment/roster-service.js";
import { truncateReportingTables } from "../../../../apps/api/src/modules/reporting-export/repositories.js";
import { SessionService, truncateSessionTables } from "../../../../apps/api/src/modules/session-management/session-service.js";
import { createPool, setPool, closePool, type DbPool } from "../../../../apps/api/src/infra/db.js";
import { runMigrations } from "../../../../apps/api/src/infra/migrate.js";
import { buildApp } from "../../../../apps/api/src/server.js";
import { resetClock, setClock, now, advanceClock } from "../../../../apps/api/src/infra/clock.js";
import { withIntegrationTestDbReset } from "../../../../apps/api/src/infra/integration-test-lock.js";
import {
  ADMIN_PASSWORD,
  CLASS_HESD_01,
  CLASS_HESD_02,
  DEFAULT_PASSWORD,
  IN_RADIUS_LAT,
  IN_RADIUS_LNG,
  ROOM_LAT,
  ROOM_LNG,
  SUBJECT_SWE_101,
  SUBJECT_SWE_102,
} from "./constants.js";
import { buildCsv, multipartPayload } from "./multipart.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

export interface AuthSession {
  userId: string;
  cookie: string;
  email?: string;
  password?: string;
  institutionalId?: string;
}

export class E2eContext {
  db!: DbPool;
  app!: FastifyInstance;
  store!: SessionStore;
  sessionService!: SessionService;
  notificationService!: NotificationService;

  async setup(): Promise<void> {
    this.db = createPool(DEFAULT_DATABASE_URL);
    setPool(this.db);
    await runMigrations(this.db);
    this.app = await buildApp({ db: this.db, logger: false });
    this.store = new SessionStore(this.db);
    this.sessionService = new SessionService(this.db);
    this.notificationService = new NotificationService(this.db);
  }

  async teardown(): Promise<void> {
    await this.sessionService.qr.stopAll();
    resetClock();
    await this.app.close();
    await closePool();
  }

  async resetDb(afterTruncate?: () => Promise<void>): Promise<void> {
    await withIntegrationTestDbReset(this.db, async () => {
      await this.sessionService.qr.stopAll();
      await truncateCheckInTables(this.db);
      await truncateNotificationTables(this.db);
      await truncateSessionTables(this.db);
      await truncateReportingTables(this.db);
      await truncateRosterTables(this.db);
      await truncateAuthTables(this.db);
      resetClock();
      await this.db.query(
        `INSERT INTO policy_settings (key, value) VALUES ($1, '20')
         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
        [POLICY_KEY_ABSENCE_THRESHOLD],
      );
      if (afterTruncate) await afterTruncate();
    });
  }

  async seedReferenceData(): Promise<void> {
    await this.db.query(
      `INSERT INTO classes (id, code, name) VALUES
       ($1, 'HESD-01', 'HESD Cohort A'),
       ($2, 'HESD-02', 'HESD Cohort B')
       ON CONFLICT (id) DO NOTHING`,
      [CLASS_HESD_01, CLASS_HESD_02],
    );
    await this.db.query(
      `INSERT INTO subjects (id, code, name) VALUES
       ($1, 'SWE-101', 'Software Engineering 101'),
       ($2, 'SWE-102', 'Software Engineering 102')
       ON CONFLICT (id) DO NOTHING`,
      [SUBJECT_SWE_101, SUBJECT_SWE_102],
    );
  }

  async seedAdmin(): Promise<AuthSession> {
    const passwordHash = await hashPassword(ADMIN_PASSWORD);
    const userId = randomUUID();
    const email = `admin-${userId.slice(0, 8)}@example.edu.vn`;
    await this.db.query(
      `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, 'Admin User', $3, $4, $5, true)`,
      [userId, `ADMIN-${userId.slice(0, 8)}`, email, passwordHash, UserRole.TrainingOfficeAdmin],
    );
    const session = await this.store.createSession(userId);
    return {
      userId,
      email,
      password: ADMIN_PASSWORD,
      cookie: `${SESSION_COOKIE_NAME}=${session.id}`,
    };
  }

  async seedInstructor(assigned = true): Promise<AuthSession> {
    const suffix = randomUUID().slice(0, 8);
    const userId = await createTestUser(this.db, {
      institutionalId: `GV-${suffix}`,
      displayName: "Instructor One",
      email: `instructor-${suffix}@example.edu.vn`,
      role: UserRole.Instructor,
    });
    if (assigned) {
      await this.db.query(
        `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
         VALUES ($1, $2, $3)`,
        [userId, CLASS_HESD_01, SUBJECT_SWE_101],
      );
    }
    const session = await this.store.createSession(userId);
    return {
      userId,
      cookie: `${SESSION_COOKIE_NAME}=${session.id}`,
      email: `instructor-${suffix}@example.edu.vn`,
    };
  }

  async seedStudent(
    institutionalId: string,
    email: string,
    displayName = "Test Student",
    password = DEFAULT_PASSWORD,
  ): Promise<AuthSession> {
    const passwordHash = await hashPassword(password);
    const userId = randomUUID();
    await this.db.query(
      `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, $6, true)`,
      [userId, institutionalId, displayName, email, passwordHash, UserRole.Student],
    );
    const session = await this.store.createSession(userId);
    return {
      userId,
      institutionalId,
      email,
      password,
      cookie: `${SESSION_COOKIE_NAME}=${session.id}`,
    };
  }

  async enrollStudent(studentId: string, classId = CLASS_HESD_01, subjectId = SUBJECT_SWE_101): Promise<void> {
    await this.db.query(
      `INSERT INTO enrollments (student_id, class_id, subject_id) VALUES ($1, $2, $3)`,
      [studentId, classId, subjectId],
    );
  }

  async login(email: string, password: string, returnUrl?: string): Promise<AuthSession> {
    const response = await this.app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email, password, returnUrl },
    });
    if (response.statusCode !== 200) {
      throw new Error(`Login failed: ${response.statusCode} ${response.body}`);
    }
    const body = response.json<{ user: { id: string }; redirectTo?: string }>();
    const setCookie = response.headers["set-cookie"];
    const cookieHeader = Array.isArray(setCookie) ? setCookie[0] : setCookie;
    const match = cookieHeader?.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`));
    const sessionId = match?.[1] ?? "";
    return {
      userId: body.user.id,
      email,
      password,
      cookie: `${SESSION_COOKIE_NAME}=${sessionId}`,
    };
  }

  async importRoster(admin: AuthSession, rows: string[]): Promise<{ batchId: string; successRows: number }> {
    const { payload, contentType } = multipartPayload(buildCsv(rows));
    const importRes = await this.app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: { cookie: admin.cookie, "content-type": contentType },
      payload,
    });
    if (importRes.statusCode !== 202) {
      throw new Error(`Roster import failed: ${importRes.statusCode} ${importRes.body}`);
    }
    const { batchId } = importRes.json<{ batchId: string }>();
    for (let i = 0; i < 30; i += 1) {
      const poll = await this.app.inject({
        method: "GET",
        url: `/api/v1/roster/imports/${batchId}`,
        headers: { cookie: admin.cookie },
      });
      const body = poll.json<{ status: string; successRows: number; errorRows: number }>();
      if (body.status === "Completed" || body.status === "Failed") {
        return { batchId, successRows: body.successRows };
      }
      await new Promise((r) => setTimeout(r, 50));
    }
    throw new Error("Roster import batch did not complete");
  }

  futureStart(offsetMs = 60 * 60 * 1000): string {
    return new Date(now().getTime() + offsetMs).toISOString();
  }

  checkInPayload(tokenId: string, overrides: Record<string, unknown> = {}) {
    return {
      tokenId,
      latitude: IN_RADIUS_LAT,
      longitude: IN_RADIUS_LNG,
      spoofMetadata: { mockLocationDetected: false, accuracyMeters: 12.5, platform: "android" },
      ...overrides,
    };
  }

  async createDraftSession(instructor: AuthSession): Promise<string> {
    const response = await this.app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: instructor.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "E2E Workshop",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        gpsRadiusMeters: 100,
        scheduledStart: this.futureStart(),
      },
    });
    if (response.statusCode !== 201) {
      throw new Error(`Create session failed: ${response.statusCode} ${response.body}`);
    }
    return response.json<{ id: string }>().id;
  }

  async openSession(sessionId: string, instructor: AuthSession): Promise<void> {
    const response = await this.app.inject({
      method: "POST",
      url: `/api/v1/sessions/${sessionId}/open`,
      headers: { cookie: instructor.cookie },
    });
    if (response.statusCode !== 200) {
      throw new Error(`Open session failed: ${response.statusCode} ${response.body}`);
    }
  }

  async closeSession(sessionId: string, instructor: AuthSession): Promise<void> {
    const response = await this.app.inject({
      method: "POST",
      url: `/api/v1/sessions/${sessionId}/close`,
      headers: { cookie: instructor.cookie },
    });
    if (response.statusCode !== 200) {
      throw new Error(`Close session failed: ${response.statusCode} ${response.body}`);
    }
  }

  async getCurrentQr(sessionId: string, instructor: AuthSession): Promise<{ tokenId: string; secondsRemaining: number }> {
    const response = await this.app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/qr/current`,
      headers: { cookie: instructor.cookie },
    });
    if (response.statusCode !== 200) {
      throw new Error(`Get QR failed: ${response.statusCode} ${response.body}`);
    }
    return response.json<{ tokenId: string; secondsRemaining: number }>();
  }

  async checkIn(student: AuthSession, tokenId: string, overrides: Record<string, unknown> = {}) {
    return this.app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: this.checkInPayload(tokenId, overrides),
    });
  }

  async waitForThresholdEvaluation(sessionId: string): Promise<void> {
    await this.notificationService.evaluateAbsenceThresholds(sessionId);
  }

  expireQrToken(): void {
    advanceClock(QR_TOKEN_TTL_MS + 1000);
  }

  setFixedClock(iso: string): void {
    setClock(new Date(iso));
  }
}

export const ctx = new E2eContext();
