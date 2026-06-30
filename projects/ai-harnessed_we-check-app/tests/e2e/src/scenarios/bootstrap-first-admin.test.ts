import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { ErrorCode, SESSION_COOKIE_NAME, UserRole } from "@wecheck/domain";
import { ctx } from "../support/e2e-context.js";

/**
 * Bootstrap first admin — deployment gate (testing-plan TS-21d)
 * Traceability: AC-17 FR-17 BR-13 NFR-16
 * Cases: TC-AC-17-001 TC-AC-17-006 TC-AC-17-007 TC-AC-17-008 TC-FR-17-001
 * TC-FR-17-005 TC-FR-17-006 TC-FR-17-007 TC-FR-17-009 TC-NFR-16-018
 */
describe("Bootstrap first admin (AC-17, FR-17, NFR-16)", () => {
  before(async () => {
    await ctx.setup();
  });

  after(async () => {
    await ctx.teardown();
  });

  it("GET /setup/status needsSetup true on empty DB; POST creates admin + session (TC-AC-17-001, TC-FR-17-001, TC-NFR-16-018)", async () => {
    await ctx.resetDb();

    const statusRes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/setup/status",
    });
    assert.equal(statusRes.statusCode, 200);
    assert.deepEqual(statusRes.json(), { needsSetup: true });

    const createRes = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "ADMIN001",
        displayName: "Bootstrap Admin",
        email: "bootstrap-admin@example.edu.vn",
        password: "BootstrapPass8",
      },
    });
    assert.equal(createRes.statusCode, 201);

    const cookieHeader = createRes.headers["set-cookie"];
    const cookie = Array.isArray(cookieHeader) ? cookieHeader[0] : cookieHeader;
    assert.ok(cookie?.includes(SESSION_COOKIE_NAME));

    const body = createRes.json<{
      user: { role: string; email: string };
      session: { expiresAt: string };
    }>();
    assert.equal(body.user.role, UserRole.TrainingOfficeAdmin);
    assert.equal(body.user.email, "bootstrap-admin@example.edu.vn");

    const expiresAt = new Date(body.session.expiresAt);
    const hoursUntilExpiry = (expiresAt.getTime() - Date.now()) / (1000 * 60 * 60);
    assert.ok(hoursUntilExpiry >= 7.9 && hoursUntilExpiry <= 8.1);

    const meRes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: cookie ?? "" },
    });
    assert.equal(meRes.statusCode, 200);
    assert.equal(meRes.json<{ role: string }>().role, UserRole.TrainingOfficeAdmin);

    const afterStatus = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/setup/status",
    });
    assert.deepEqual(afterStatus.json(), { needsSetup: false });
  });

  it("repeat POST /setup/first-admin returns 403 SetupAlreadyComplete (TC-AC-17-008, TC-FR-17-007, TC-AC-17-011)", async () => {
    await ctx.resetDb();

    const first = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "ADMIN002",
        displayName: "First Admin",
        email: "first-admin@example.edu.vn",
        password: "FirstAdminPass8",
      },
    });
    assert.equal(first.statusCode, 201);

    const repeat = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "ADMIN003",
        displayName: "Second Admin",
        email: "second-admin@example.edu.vn",
        password: "SecondAdmin8",
      },
    });
    assert.equal(repeat.statusCode, 403);
    assert.equal(repeat.json<{ errorCode: string }>().errorCode, ErrorCode.SetupAlreadyComplete);
  });

  it("weak password returns 422 and leaves needsSetup true (TC-FR-17-009)", async () => {
    await ctx.resetDb();

    const createRes = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "ADMIN004",
        displayName: "Weak Password",
        email: "weak@example.edu.vn",
        password: "short",
      },
    });
    assert.equal(createRes.statusCode, 422);
    assert.equal(createRes.json<{ errorCode: string }>().errorCode, ErrorCode.ValidationFailed);

    const statusRes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/setup/status",
    });
    assert.deepEqual(statusRes.json(), { needsSetup: true });
  });

  it("invalid institutionalId returns 422 on empty DB (TC-FR-17-008)", async () => {
    await ctx.resetDb();

    const createRes = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/setup/first-admin",
      payload: {
        institutionalId: "AB",
        displayName: "Invalid ID",
        email: "invalid-id@example.edu.vn",
        password: "InvalidIdPass8",
      },
    });
    assert.equal(createRes.statusCode, 422);
    assert.equal(createRes.json<{ errorCode: string }>().errorCode, ErrorCode.ValidationFailed);

    const statusRes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/setup/status",
    });
    assert.deepEqual(statusRes.json(), { needsSetup: true });
  });
});
