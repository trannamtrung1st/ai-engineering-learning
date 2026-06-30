import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { UserRole } from "@wecheck/domain";
import { ctx } from "../support/e2e-context.js";
import { ADMIN_PASSWORD } from "../support/constants.js";

/**
 * Admin hub deep links — AC-18 FR-18
 * Cases: TC-AC-18-008 TC-AC-18-014 TC-FR-18-009 TC-FR-18-010
 */
describe("admin hub deep links (AC-18, FR-18)", () => {
  before(async () => {
    await ctx.setup();
  });

  after(async () => {
    await ctx.teardown();
  });

  it("TC-AC-18-014 / TC-FR-18-009: admin login redirectTo is /admin hub not /admin/users", async () => {
    await ctx.resetDb();
    const admin = await ctx.seedAdmin();

    const login = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email: admin.email, password: ADMIN_PASSWORD },
    });
    assert.equal(login.statusCode, 200);
    const body = login.json<{ redirectTo: string; user: { role: string } }>();
    assert.equal(body.user.role, UserRole.TrainingOfficeAdmin);
    assert.equal(body.redirectTo, "/admin");
    assert.notEqual(body.redirectTo, "/admin/users");
  });

  it("TC-AC-18-008: admin can access permitted admin report and user routes", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();

    for (const path of ["/api/v1/users", "/api/v1/reports/summary?from=2026-06-01&to=2026-06-30"]) {
      const res = await ctx.app.inject({
        method: "GET",
        url: path,
        headers: { cookie: admin.cookie },
      });
      assert.equal(res.statusCode, 200, `expected 200 for ${path}`);
    }
  });
});
