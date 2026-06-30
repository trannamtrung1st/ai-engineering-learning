import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { UserRole } from "@wecheck/domain";
import { ctx } from "../support/e2e-context.js";
import { ADMIN_PASSWORD, DEFAULT_PASSWORD } from "../support/constants.js";

/**
 * Navigation permission gates — AC-18 FR-18 BR-14 NFR-11
 * Cases: TC-AC-18-001 TC-AC-18-004 TC-AC-18-005 TC-AC-18-006
 * TC-FR-18-001 TC-FR-18-005 TC-FR-18-006 TC-FR-18-007
 * TC-BR-14-001 TC-BR-14-004 TC-BR-14-005 TC-BR-14-012
 */
describe("nav permission gate (AC-18, FR-18, BR-14, NFR-11)", () => {
  before(async () => {
    await ctx.setup();
  });

  after(async () => {
    await ctx.teardown();
  });

  it("TC-AC-18-001 / TC-FR-18-001: instructor denied admin user list API (TS-21f)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();

    const me = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: instructor.cookie },
    });
    assert.equal(me.statusCode, 200);
    const meBody = me.json<{ role: string }>();
    assert.equal(meBody.role, UserRole.Instructor);

    const denied = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/users",
      headers: { cookie: instructor.cookie },
    });
    assert.equal(denied.statusCode, 403);
    assert.equal(denied.json<{ errorCode: string }>().errorCode, "Forbidden");

    const allowed = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/sessions",
      headers: { cookie: instructor.cookie },
    });
    assert.equal(allowed.statusCode, 200);
  });

  it("TC-FR-18-005: POST /auth/login redirectTo resolves to role home hubs", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();
    const student = await ctx.seedStudent(
      `SV-${randomUUID().slice(0, 8)}`,
      `student-${randomUUID().slice(0, 8)}@example.edu.vn`,
    );

    const instructorEmail = `instructor-${randomUUID().slice(0, 8)}@example.edu.vn`;
    const createInstructor = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers: { cookie: admin.cookie },
      payload: {
        institutionalId: `GV-${randomUUID().slice(0, 8)}`,
        displayName: "Instructor Nav",
        email: instructorEmail,
        password: DEFAULT_PASSWORD,
        role: UserRole.Instructor,
      },
    });
    assert.equal(createInstructor.statusCode, 201);

    const studentLogin = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email: student.email, password: student.password },
    });
    assert.equal(studentLogin.statusCode, 200);
    assert.equal(studentLogin.json<{ redirectTo: string }>().redirectTo, "/check-in");

    const instructorLogin = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email: instructorEmail, password: DEFAULT_PASSWORD },
    });
    assert.equal(instructorLogin.statusCode, 200);
    assert.equal(instructorLogin.json<{ redirectTo: string }>().redirectTo, "/sessions");

    const adminLogin = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email: admin.email, password: ADMIN_PASSWORD },
    });
    assert.equal(adminLogin.statusCode, 200);
    assert.equal(adminLogin.json<{ redirectTo: string }>().redirectTo, "/admin");
  });

  it("TC-FR-18-006 / TC-BR-14-004: GET /auth/me returns role and permissions", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();
    const instructor = await ctx.seedInstructor();
    const student = await ctx.seedStudent(
      `SV-${randomUUID().slice(0, 8)}`,
      `student-${randomUUID().slice(0, 8)}@example.edu.vn`,
    );

    const studentMe = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: student.cookie },
    });
    const studentBody = studentMe.json<{ role: string; permissions: string[] }>();
    assert.equal(studentBody.role, UserRole.Student);
    assert.ok(studentBody.permissions.includes("checkin:submit"));

    const instructorMe = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: instructor.cookie },
    });
    const instructorBody = instructorMe.json<{ role: string; permissions: string[] }>();
    assert.equal(instructorBody.role, UserRole.Instructor);
    assert.ok(instructorBody.permissions.includes("session:read"));

    const adminMe = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: admin.cookie },
    });
    const adminBody = adminMe.json<{ role: string; permissions: string[] }>();
    assert.equal(adminBody.role, UserRole.TrainingOfficeAdmin);
    assert.ok(adminBody.permissions.includes("user:write"));
    assert.ok(adminBody.permissions.includes("report:export"));
  });

  it("TC-AC-18-005 / TC-AC-18-006: student and instructor denied admin API surfaces", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const student = await ctx.seedStudent(
      `SV-${randomUUID().slice(0, 8)}`,
      `student-${randomUUID().slice(0, 8)}@example.edu.vn`,
    );
    const instructor = await ctx.seedInstructor();

    const studentUsers = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/users",
      headers: { cookie: student.cookie },
    });
    assert.equal(studentUsers.statusCode, 403);

    const instructorExport = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: instructor.cookie, "content-type": "application/json" },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-06-01",
        to: "2026-06-30",
      },
    });
    assert.equal(instructorExport.statusCode, 403);
    assert.equal(instructorExport.json<{ errorCode: string }>().errorCode, "ExportNotAllowed");
  });

  it("TC-BR-14-012: instructor lacks report:export in permissions and export API", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const me = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: instructor.cookie },
    });
    const permissions = me.json<{ permissions: string[] }>().permissions;
    assert.ok(!permissions.includes("report:export"));
  });
});
