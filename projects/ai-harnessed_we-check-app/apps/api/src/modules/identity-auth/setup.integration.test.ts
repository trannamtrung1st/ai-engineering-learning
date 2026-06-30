import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { ErrorCode, SESSION_COOKIE_NAME, UserRole } from "@wecheck/domain";
import { createPool, setPool, closePool, type DbPool } from "../../infra/db.js";
import { runMigrations } from "../../infra/migrate.js";
import { buildApp } from "../../server.js";
import { SessionStore, truncateAuthTables } from "../../auth/session-store.js";
import { withIntegrationTestDbReset } from "../../infra/integration-test-lock.js";
import { hashPassword, isPasswordHash } from "./password-hasher.js";
import { UserRepository } from "./user-repository.js";
import { SetupService } from "./setup/setup-service.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

const validBootstrapPayload = {
  institutionalId: "BOOTADMIN1",
  displayName: "Nguyễn Văn Admin",
  email: "bootstrap-admin@example.edu.vn",
  password: "BootstrapPass8",
};

/**
 * Traceability: AC-17 FR-17 BR-13
 * Cases: TC-AC-17-002 TC-AC-17-003 TC-AC-17-004 TC-AC-17-005 TC-AC-17-006
 * TC-AC-17-007 TC-AC-17-008 TC-AC-17-010 TC-AC-17-011 TC-AC-17-012
 * TC-BR-13-002 TC-BR-13-003 TC-BR-13-004 TC-BR-13-008 TC-BR-13-011 TC-BR-13-012
 * TC-FR-17-002 TC-FR-17-003 TC-FR-17-004 TC-FR-17-005 TC-FR-17-006 TC-FR-17-007
 * TC-FR-17-009 TC-FR-17-010 TC-NFR-14-011 TC-NFR-16-389
 */
describe("identity-auth bootstrap setup (AC-17, FR-17, BR-13)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let users: UserRepository;
  let setupService: SetupService;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    users = new UserRepository(db);
    setupService = new SetupService(db, users, store);
  });

  after(async () => {
    await app.close();
    await closePool();
  });

  async function resetDb(): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateAuthTables(db);
    });
  }

  function extractSessionCookie(
    setCookie: string | string[] | undefined,
  ): string {
    const cookieHeader = Array.isArray(setCookie) ? setCookie[0] : setCookie;
    const match = cookieHeader?.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`));
    const sessionId = match?.[1] ?? "";
    return `${SESSION_COOKIE_NAME}=${sessionId}`;
  }

  it("SetupService.getStatus returns needsSetup true when users table is empty (TC-AC-17-002, TC-FR-17-002, TC-BR-13-002)", async () => {
    await resetDb();
    const countRow = await db.query<{ count: string }>(
      "SELECT COUNT(*)::text AS count FROM users",
    );
    assert.equal(Number.parseInt(countRow.rows[0]?.count ?? "0", 10), 0);

    const status = await setupService.getStatus();
    assert.equal(status.needsSetup, true);

    await setupService.createFirstAdmin(validBootstrapPayload);
    const after = await setupService.getStatus();
    assert.equal(after.needsSetup, false);
  });

  it("createFirstAdmin persists TrainingOfficeAdmin, session, and rejects repeat (TC-AC-17-003, TC-FR-17-003, TC-BR-13-003)", async () => {
    await resetDb();
    const password = "FirstAdminPass8";
    const result = await setupService.createFirstAdmin({
      institutionalId: "BOOTADMIN2",
      displayName: "Admin Two",
      email: "bootstrap-two@example.edu.vn",
      password,
    });

    assert.equal(result.user.role, UserRole.TrainingOfficeAdmin);
    assert.equal(result.session.userId, result.user.id);

    const userRows = await db.query<{ role: string; password_hash: string }>(
      "SELECT role, password_hash FROM users",
    );
    assert.equal(userRows.rowCount, 1);
    assert.equal(userRows.rows[0]?.role, UserRole.TrainingOfficeAdmin);
    assert.ok(isPasswordHash(userRows.rows[0]?.password_hash ?? ""));

    const sessionRows = await db.query<{ user_id: string }>(
      "SELECT user_id FROM auth_sessions WHERE user_id = $1",
      [result.user.id],
    );
    assert.equal(sessionRows.rowCount, 1);

    await assert.rejects(
      () =>
        setupService.createFirstAdmin({
          institutionalId: "BOOTADMIN3",
          displayName: "Admin Three",
          email: "bootstrap-three@example.edu.vn",
          password: "AnotherPass8",
        }),
      (error: unknown) => {
        assert.ok(error instanceof Error);
        assert.equal(
          (error as { errorCode?: string }).errorCode,
          ErrorCode.SetupAlreadyComplete,
        );
        return true;
      },
    );

    const countAfter = await users.count();
    assert.equal(countAfter, 1);
  });

  it("deployment gate transitions needsSetup true to false (TC-AC-17-005, TC-FR-17-004, TC-BR-13-004)", async () => {
    await resetDb();
    const before = await setupService.getStatus();
    assert.equal(before.needsSetup, true);
    assert.equal(await users.count(), 0);

    await setupService.createFirstAdmin({
      institutionalId: "BOOTADMIN4",
      displayName: "Gate Admin",
      email: "gate-admin@example.edu.vn",
      password: "GateAdminPass8",
    });

    assert.equal(await users.count(), 1);
    const after = await setupService.getStatus();
    assert.equal(after.needsSetup, false);

    await assert.rejects(
      () =>
        setupService.createFirstAdmin({
          institutionalId: "BOOTADMIN5",
          displayName: "Late Admin",
          email: "late-admin@example.edu.vn",
          password: "LateAdminPass8",
        }),
      (error: unknown) => {
        assert.ok(error instanceof Error);
        assert.equal(
          (error as { errorCode?: string }).errorCode,
          ErrorCode.SetupAlreadyComplete,
        );
        return true;
      },
    );
  });

  it("GET /setup/status returns needsSetup boolean (TC-AC-17-006, TC-FR-17-005, TC-BR-13-005)", async () => {
    await resetDb();
    const emptyRes = await app.inject({
      method: "GET",
      url: "/api/v1/setup/status",
    });
    assert.equal(emptyRes.statusCode, 200);
    assert.deepEqual(emptyRes.json(), { needsSetup: true });

    await app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "BOOTADMIN6",
        displayName: "Status Admin",
        email: "status-admin@example.edu.vn",
        password: "StatusAdmin8",
      },
    });

    const seededRes = await app.inject({
      method: "GET",
      url: "/api/v1/setup/status",
    });
    assert.equal(seededRes.statusCode, 200);
    assert.deepEqual(seededRes.json(), { needsSetup: false });
  });

  it("POST /setup/first-admin returns 201 with session cookie and auth/me works (TC-AC-17-007, TC-BR-13-006, TC-FR-17-006)", async () => {
    await resetDb();
    const email = "http-bootstrap@example.edu.vn";
    const createRes = await app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "BOOTADMIN7",
        displayName: "HTTP Admin",
        email,
        password: "HttpAdminPass8",
      },
    });
    assert.equal(createRes.statusCode, 201);
    const cookie = extractSessionCookie(createRes.headers["set-cookie"]);
    assert.ok(cookie.includes(SESSION_COOKIE_NAME));

    const body = createRes.json<{
      user: { role: string; email: string; password?: string };
      session: { id: string; expiresAt: string };
    }>();
    assert.equal(body.user.role, UserRole.TrainingOfficeAdmin);
    assert.equal(body.user.email, email);
    assert.equal("password" in body.user, false);
    assert.ok(body.session.id);
    assert.ok(body.session.expiresAt);

    const meRes = await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie },
    });
    assert.equal(meRes.statusCode, 200);
    const me = meRes.json<{ email: string; role: string }>();
    assert.equal(me.email, email);
    assert.equal(me.role, UserRole.TrainingOfficeAdmin);
  });

  it("repeat POST /setup/first-admin returns 403 SetupAlreadyComplete (TC-AC-17-004, TC-AC-17-008, TC-AC-17-011, TC-FR-17-007, TC-BR-13-007, TC-BR-13-010)", async () => {
    await resetDb();
    const first = await app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: validBootstrapPayload,
    });
    assert.equal(first.statusCode, 201);

    const status = await app.inject({
      method: "GET",
      url: "/api/v1/setup/status",
    });
    assert.deepEqual(status.json(), { needsSetup: false });

    const repeat = await app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "BOOTOTHER1",
        displayName: "Other Admin",
        email: "other-admin@example.edu.vn",
        password: "OtherAdminPass8",
      },
    });
    assert.equal(repeat.statusCode, 403);
    const err = repeat.json<{ errorCode: string; message: string }>();
    assert.equal(err.errorCode, ErrorCode.SetupAlreadyComplete);
    assert.ok(err.message.length > 0);
    assert.equal(await users.count(), 1);
  });

  it("bootstrap blocked when any user exists including Student (TC-BR-13-008)", async () => {
    await resetDb();
    const passwordHash = await hashPassword("StudentPass8");
    await db.query(
      `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, $6, true)`,
      [
        randomUUID(),
        "BOOTSTU001",
        "Student Only",
        "student-only@example.edu.vn",
        passwordHash,
        UserRole.Student,
      ],
    );

    const status = await setupService.getStatus();
    assert.equal(status.needsSetup, false);

    await assert.rejects(
      () =>
        setupService.createFirstAdmin({
          institutionalId: "BOOTADMIN8",
          displayName: "Blocked Admin",
          email: "blocked-admin@example.edu.vn",
          password: "BlockedAdmin8",
        }),
      (error: unknown) => {
        assert.ok(error instanceof Error);
        assert.equal(
          (error as { errorCode?: string }).errorCode,
          ErrorCode.SetupAlreadyComplete,
        );
        return true;
      },
    );

    const count = await users.count();
    assert.equal(count, 1);
    const roleRow = await db.query<{ role: string }>(
      "SELECT role FROM users LIMIT 1",
    );
    assert.equal(roleRow.rows[0]?.role, UserRole.Student);
  });

  it("weak password returns 422 and leaves needsSetup true (TC-FR-17-009, TC-NFR-14-020)", async () => {
    await resetDb();
    const res = await app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "BOOTADMIN9",
        displayName: "Weak Pass",
        email: "weak-pass@example.edu.vn",
        password: "short",
      },
    });
    assert.equal(res.statusCode, 422);
    const err = res.json<{ errorCode: string; details?: { field: string }[] }>();
    assert.equal(err.errorCode, ErrorCode.ValidationFailed);
    assert.ok(err.details?.some((d) => d.field === "password"));
    assert.equal(await users.count(), 0);
    const status = await setupService.getStatus();
    assert.equal(status.needsSetup, true);
  });

  it("parallel POST /setup/first-admin creates at most one admin (TC-AC-17-012, TC-AC-17-010, TC-BR-13-011, TC-BR-13-012, TC-FR-17-010)", async () => {
    await resetDb();
    const payloads = [
      {
        institutionalId: "BOOTPARA01",
        displayName: "Parallel One",
        email: "parallel-one@example.edu.vn",
        password: "ParallelPass1",
      },
      {
        institutionalId: "BOOTPARA02",
        displayName: "Parallel Two",
        email: "parallel-two@example.edu.vn",
        password: "ParallelPass2",
      },
      {
        institutionalId: "BOOTPARA03",
        displayName: "Parallel Three",
        email: "dup@example.edu.vn",
        password: "ParallelPass3",
      },
      {
        institutionalId: "BOOTPARA04",
        displayName: "Parallel Four",
        email: "dup@example.edu.vn",
        password: "ParallelPass4",
      },
    ];

    const responses = await Promise.all(
      payloads.map((payload) =>
        app.inject({
          method: "POST",
          url: "/api/v1/setup/first-admin",
          payload,
        }),
      ),
    );

    const created = responses.filter((r) => r.statusCode === 201);
    assert.equal(created.length, 1);
    assert.ok(extractSessionCookie(created[0]!.headers["set-cookie"]));

    const rejected = responses.filter((r) => r.statusCode !== 201);
    assert.equal(rejected.length, payloads.length - 1);
    for (const res of rejected) {
      assert.ok(
        res.statusCode === 403 || res.statusCode === 422,
        `expected 403 or 422, got ${res.statusCode}`,
      );
      if (res.statusCode === 403) {
        assert.equal(
          res.json<{ errorCode: string }>().errorCode,
          ErrorCode.SetupAlreadyComplete,
        );
      }
    }

    assert.equal(await users.count(), 1);
    const adminRow = await db.query<{ role: string }>(
      "SELECT role FROM users LIMIT 1",
    );
    assert.equal(adminRow.rows[0]?.role, UserRole.TrainingOfficeAdmin);

    const status = await setupService.getStatus();
    assert.equal(status.needsSetup, false);
  });

  it("bootstrap password stored hashed and login works (TC-NFR-14-019, TC-NFR-14-011)", async () => {
    await resetDb();
    const password = "BootstrapPass8";
    const email = "hash-bootstrap@example.edu.vn";
    await app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "BOOTHASH01",
        displayName: "Hash Admin",
        email,
        password,
      },
    });

    const row = await db.query<{ password_hash: string }>(
      "SELECT password_hash FROM users WHERE email = $1",
      [email],
    );
    const hash = row.rows[0]?.password_hash ?? "";
    assert.ok(isPasswordHash(hash));
    assert.notEqual(hash, password);

    const loginRes = await app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email, password },
    });
    assert.equal(loginRes.statusCode, 200);
  });

  it("bootstrap session uses default 8-hour inactivity window (TC-NFR-16-389)", async () => {
    await resetDb();
    const createRes = await app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "BOOTSESS01",
        displayName: "Session Admin",
        email: "session-bootstrap@example.edu.vn",
        password: "SessionAdmin8",
      },
    });
    assert.equal(createRes.statusCode, 201);
    const body = createRes.json<{ session: { expiresAt: string } }>();
    const expiresAt = new Date(body.session.expiresAt);
    const hoursUntilExpiry =
      (expiresAt.getTime() - Date.now()) / (1000 * 60 * 60);
    assert.ok(hoursUntilExpiry > 7 && hoursUntilExpiry <= 8.1);
  });

  it("records bootstrap audit log with actor and reason (AC-17)", async () => {
    await resetDb();
    const result = await setupService.createFirstAdmin({
      institutionalId: "BOOTAUDIT1",
      displayName: "Audit Admin",
      email: "audit-bootstrap@example.edu.vn",
      password: "AuditAdminPass8",
    });

    const audit = await db.query<{ action: string; actor_id: string; reason: string }>(
      `SELECT action, actor_id, reason FROM user_audit_logs
       WHERE user_id = $1 AND action = 'bootstrap_first_admin'`,
      [result.user.id],
    );
    assert.equal(audit.rowCount, 1);
    assert.equal(audit.rows[0]?.actor_id, result.user.id);
    assert.equal(audit.rows[0]?.reason, "First deployment bootstrap");
  });
});
