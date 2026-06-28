import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { ErrorCode, SESSION_COOKIE_NAME, UserRole } from "@wecheck/domain";
import { createPool, setPool, closePool, type DbPool } from "../../infra/db.js";
import { runMigrations } from "../../infra/migrate.js";
import { buildApp } from "../../server.js";
import { SessionStore, truncateAuthTables } from "../../auth/session-store.js";
import { resetClock, setClock } from "../../infra/clock.js";
import { hashPassword, isPasswordHash } from "./password-hasher.js";
import { UserRepository } from "./user-repository.js";
import { AuthService } from "./auth-service.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

/**
 * Traceability: AC-01 AC-02 FR-01 FR-02 BR-06 NFR-14 NFR-16
 * Cases: TC-AC-01-002 TC-AC-01-006 TC-AC-02-004 TC-AC-02-005 TC-NFR-14-001
 * TC-NFR-14-002 TC-NFR-14-004 TC-NFR-16-002 TC-NFR-16-003 TC-BR-06-006 TC-FR-01-002
 */
describe("identity-auth integration (AC-01, AC-02, FR-01, FR-02, BR-06, NFR-14, NFR-16)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let users: UserRepository;
  let authService: AuthService;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    users = new UserRepository(db);
    authService = new AuthService(users, store);
  });

  after(async () => {
    resetClock();
    await app.close();
    await closePool();
  });

  async function resetDb(): Promise<void> {
    await truncateAuthTables(db);
    resetClock();
  }

  async function seedAdmin(): Promise<{ email: string; password: string }> {
    const password = "AdminPass123";
    const passwordHash = await hashPassword(password);
    await db.query(
      `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, $6, true)`,
      [
        "00000000-0000-4000-8000-000000000001",
        "ADMIN001",
        "Admin User",
        "admin@example.edu.vn",
        passwordHash,
        UserRole.TrainingOfficeAdmin,
      ],
    );
    return { email: "admin@example.edu.vn", password };
  }

  async function loginAs(
    email: string,
    password: string,
  ): Promise<{ sessionId: string; cookie: string }> {
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email, password },
    });
    assert.equal(response.statusCode, 200);
    const setCookie = response.headers["set-cookie"];
    const cookieHeader = Array.isArray(setCookie) ? setCookie[0] : setCookie;
    const match = cookieHeader?.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`));
    const sessionId = match?.[1] ?? "";
    return { sessionId, cookie: `${SESSION_COOKIE_NAME}=${sessionId}` };
  }

  it("UserService.provision persists hashed password (TC-AC-01-002, TC-NFR-14-001, FR-01)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    const createRes = await app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers: { cookie: adminSession.cookie },
      payload: {
        institutionalId: "SV2026999",
        displayName: "Nguyễn Văn A",
        email: "student999@example.edu.vn",
        password: "StudentPass8",
        role: UserRole.Student,
      },
    });
    assert.equal(createRes.statusCode, 201);
    const body = createRes.json<{ active: boolean; role: string }>();
    assert.equal(body.active, true);
    assert.equal(body.role, UserRole.Student);
    assert.equal("password" in body, false);
    assert.equal("passwordHash" in body, false);

    const row = await db.query<{ password_hash: string }>(
      "SELECT password_hash FROM users WHERE institutional_id = $1",
      ["SV2026999"],
    );
    const hash = row.rows[0]?.password_hash ?? "";
    assert.ok(isPasswordHash(hash));
    assert.notEqual(hash, "StudentPass8");
  });

  it("AuthService.authenticate creates session with 8-hour expiry (TC-AC-02-004, TC-NFR-16-002, FR-02)", async () => {
    await resetDb();
    const t0 = new Date("2026-06-28T08:00:00.000Z");
    setClock(t0);

    const passwordHash = await hashPassword("Workshop2026!");
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      ["SV2026100", "Student", "workshop@example.edu.vn", passwordHash, UserRole.Student],
    );

    const result = await authService.authenticate({
      email: "workshop@example.edu.vn",
      password: "Workshop2026!",
    });
    assert.ok(result.session.id);

    const sessionRow = await db.query<{
      expires_at: Date;
      last_activity_at: Date;
    }>("SELECT expires_at, last_activity_at FROM auth_sessions WHERE id = $1", [
      result.session.id,
    ]);
    const expiresAt = sessionRow.rows[0]!.expires_at.getTime();
    const expected = t0.getTime() + 8 * 60 * 60 * 1000;
    assert.ok(Math.abs(expiresAt - expected) < 2000);

    setClock(new Date(t0.getTime() + 8 * 60 * 60 * 1000 + 60_000));
    await assert.rejects(
      () => authService.requireUser(result.session.id),
      (error: { errorCode?: string }) => error.errorCode === ErrorCode.SessionExpired,
    );
    resetClock();
  });

  it("session valid before 8h and expired after (TC-AC-02-005, TC-NFR-16-004, BR-06)", async () => {
    await resetDb();
    const passwordHash = await hashPassword("SessionTest8");
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      ["SV2026101", "Student", "session@example.edu.vn", passwordHash, UserRole.Student],
    );
    const auth = await authService.authenticate({
      email: "session@example.edu.vn",
      password: "SessionTest8",
    });

    const t0 = new Date("2026-06-28T08:00:00.000Z");
    await db.query(
      "UPDATE auth_sessions SET last_activity_at = $2, expires_at = $3 WHERE id = $1",
      [auth.session.id, t0, new Date(t0.getTime() + 8 * 60 * 60 * 1000)],
    );

    setClock(new Date("2026-06-28T15:59:00.000Z"));
    const valid = await authService.requireUser(auth.session.id);
    assert.equal(valid.user.email, "session@example.edu.vn");

    setClock(new Date("2026-06-28T16:01:00.000Z"));
    await assert.rejects(() => authService.requireUser(auth.session.id));
    resetClock();
  });

  it("POST /auth/login with returnUrl and GET /auth/me (TC-AC-02-002, TC-AC-02-006, FR-02)", async () => {
    await resetDb();
    const passwordHash = await hashPassword("ValidLogin8");
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      ["SV2026102", "Student", "validlogin@example.edu.vn", passwordHash, UserRole.Student],
    );

    const loginRes = await app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: {
        email: "validlogin@example.edu.vn",
        password: "ValidLogin8",
        returnUrl: "/check-in?token=test-token",
      },
    });
    assert.equal(loginRes.statusCode, 200);
    const loginBody = loginRes.json<{
      redirectTo: string;
      user: { email: string };
      session: { id: string; expiresAt: string };
    }>();
    assert.equal(loginBody.redirectTo, "/check-in?token=test-token");
    assert.ok(loginBody.session.expiresAt);

    const setCookie = loginRes.headers["set-cookie"];
    const cookieHeader = Array.isArray(setCookie) ? setCookie[0] : setCookie;
    assert.match(cookieHeader ?? "", /HttpOnly/i);

    const meRes = await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: cookieHeader?.split(";")[0] ?? "" },
    });
    assert.equal(meRes.statusCode, 200);
    assert.equal(meRes.json<{ email: string }>().email, "validlogin@example.edu.vn");
    assert.equal("passwordHash" in meRes.json(), false);
  });

  it("invalid credentials return 401 InvalidCredentials (TC-AC-02-009, BR-06)", async () => {
    await resetDb();
    const passwordHash = await hashPassword("CorrectPass8");
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      ["SV2026103", "Student", "creds@example.edu.vn", passwordHash, UserRole.Student],
    );

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email: "creds@example.edu.vn", password: "WrongPass99" },
    });
    assert.equal(response.statusCode, 401);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.InvalidCredentials,
    );
    assert.equal(response.headers["set-cookie"], undefined);
  });

  it("deactivated user login returns 403 AccountDeactivated (TC-AC-01-005, BR-06)", async () => {
    await resetDb();
    const passwordHash = await hashPassword("DeactPass8");
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, false)`,
      ["SV2026104", "Student", "deact@example.edu.vn", passwordHash, UserRole.Student],
    );

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email: "deact@example.edu.vn", password: "DeactPass8" },
    });
    assert.equal(response.statusCode, 403);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.AccountDeactivated,
    );
  });

  it("deactivating user revokes sessions (TC-AC-01-006, FR-01)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    const passwordHash = await hashPassword("ActivePass8");
    const insert = await db.query<{ id: string }>(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)
       RETURNING id`,
      ["SV2026105", "Student", "active@example.edu.vn", passwordHash, UserRole.Student],
    );
    const userId = insert.rows[0]!.id;
    const studentSession = await store.createSession(userId);

    const patchRes = await app.inject({
      method: "PATCH",
      url: `/api/v1/users/${userId}`,
      headers: { cookie: adminSession.cookie },
      payload: { active: false },
    });
    assert.equal(patchRes.statusCode, 200);
    assert.equal(patchRes.json<{ active: boolean }>().active, false);

    const revoked = await db.query<{ revoked_at: Date | null }>(
      "SELECT revoked_at FROM auth_sessions WHERE id = $1",
      [studentSession.id],
    );
    assert.ok(revoked.rows[0]?.revoked_at);

    const audit = await db.query<{ action: string }>(
      "SELECT action FROM user_audit_logs WHERE user_id = $1",
      [userId],
    );
    assert.equal(audit.rows[0]?.action, "deactivate");
  });

  it("duplicate institutionalId returns 422 (TC-AC-01-004, FR-01)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      [
        "SV2026001",
        "Existing",
        "existing@example.edu.vn",
        await hashPassword("Existing8!"),
        UserRole.Student,
      ],
    );

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers: { cookie: adminSession.cookie },
      payload: {
        institutionalId: "SV2026001",
        displayName: "Duplicate",
        email: "dup@example.edu.vn",
        password: "DupPass123",
        role: UserRole.Student,
      },
    });
    assert.equal(response.statusCode, 422);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.ValidationFailed,
    );

    const count = await db.query<{ count: string }>(
      "SELECT COUNT(*)::text AS count FROM users WHERE institutional_id = $1",
      ["SV2026001"],
    );
    assert.equal(count.rows[0]?.count, "1");
  });

  it("Student denied POST /users (TC-AC-01-007, NFR-14)", async () => {
    await resetDb();
    const passwordHash = await hashPassword("StudentPass8");
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      ["SV2026106", "Student", "student@example.edu.vn", passwordHash, UserRole.Student],
    );
    const studentSession = await loginAs("student@example.edu.vn", "StudentPass8");

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers: { cookie: studentSession.cookie },
      payload: {
        institutionalId: "SV2026107",
        displayName: "Hack",
        email: "hack@example.edu.vn",
        password: "AttemptPass8",
        role: UserRole.Student,
      },
    });
    assert.equal(response.statusCode, 403);
  });

  it("POST /auth/logout revokes session (TC-FR-02-009, FR-02)", async () => {
    await resetDb();
    const passwordHash = await hashPassword("LogoutPass8");
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      ["SV2026108", "Student", "logout@example.edu.vn", passwordHash, UserRole.Student],
    );
    const session = await loginAs("logout@example.edu.vn", "LogoutPass8");

    const logoutRes = await app.inject({
      method: "POST",
      url: "/api/v1/auth/logout",
      headers: { cookie: session.cookie },
    });
    assert.equal(logoutRes.statusCode, 204);

    const meRes = await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: session.cookie },
    });
    assert.equal(meRes.statusCode, 401);
  });

  it("password change via PATCH invalidates old password (TC-NFR-14-004, NFR-14)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    const createRes = await app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers: { cookie: adminSession.cookie },
      payload: {
        institutionalId: "SV2026109",
        displayName: "Pwd Change",
        email: "pwdchange@example.edu.vn",
        password: "OldSecure8",
        role: UserRole.Student,
      },
    });
    const userId = createRes.json<{ id: string }>().id;

    const patchRes = await app.inject({
      method: "PATCH",
      url: `/api/v1/users/${userId}`,
      headers: { cookie: adminSession.cookie },
      payload: { password: "NewSecure99" },
    });
    assert.equal(patchRes.statusCode, 200);

    const oldLogin = await app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email: "pwdchange@example.edu.vn", password: "OldSecure8" },
    });
    assert.equal(oldLogin.statusCode, 401);

    const newLogin = await app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email: "pwdchange@example.edu.vn", password: "NewSecure99" },
    });
    assert.equal(newLogin.statusCode, 200);
  });

  it("admin can configure session inactivity policy (TC-NFR-16-008, NFR-16)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    const putRes = await app.inject({
      method: "PUT",
      url: "/api/v1/policy/session-inactivity",
      headers: { cookie: adminSession.cookie },
      payload: { inactivityHours: 10 },
    });
    assert.equal(putRes.statusCode, 200);
    assert.equal(putRes.json<{ inactivityHours: number }>().inactivityHours, 10);

    const row = await db.query<{ value: string }>(
      "SELECT value FROM policy_settings WHERE key = 'session_inactivity_hours'",
    );
    assert.equal(row.rows[0]?.value, "10");
  });

  it("stale session for deactivated user rejected (TC-BR-06-006, BR-06)", async () => {
    await resetDb();
    const passwordHash = await hashPassword("StalePass8");
    const insert = await db.query<{ id: string }>(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, false)
       RETURNING id`,
      ["SV2026110", "Student", "stale@example.edu.vn", passwordHash, UserRole.Student],
    );
    const userId = insert.rows[0]!.id;
    const session = await store.createSession(userId);

    const response = await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${session.id}` },
    });
    assert.equal(response.statusCode, 401);
  });
});
