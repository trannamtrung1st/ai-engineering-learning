import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import type { FastifyInstance } from "fastify";

import { API_BASE_PATH, buildApp } from "../../index.js";
import { closeDb } from "../../db/pool.js";
import { ensureUserSchema } from "../user/repository.js";
import { ensureTestOrganizerAdmin } from "../../test-helpers/participant-user.js";

function parseError(body: string) {
  return JSON.parse(body) as {
    error: { code: string; message: string };
  };
}

describe("auth module integration", () => {
  let app: FastifyInstance;

  before(async () => {
    process.env.DATABASE_URL ??=
      "postgresql://we_event:we_event@localhost:5432/we_event";
    process.env.JWT_SECRET ??= "test-jwt-secret";
    process.env.DEV_AUTH_ENABLED = "true";

    ({ app } = await buildApp());
    await ensureUserSchema();
    await ensureTestOrganizerAdmin();
  });

  after(async () => {
    await app.close();
    await closeDb();
  });

  it("FR-32: participant can register with email and password", async () => {
    const email = `participant+${randomUUID()}@example.com`;
    const response = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: {
        email,
        password: "secure-pass-1",
        displayName: "New Participant",
      },
    });

    assert.equal(response.statusCode, 200, response.body);
    const body = JSON.parse(response.body) as {
      token: string;
      profile: {
        userId: string;
        email: string;
        displayName: string;
        roles: Array<{ role: string }>;
      };
    };
    assert.ok(body.token);
    assert.equal(body.profile.email, email);
    assert.equal(body.profile.displayName, "New Participant");
    assert.equal(body.profile.roles.length, 1);
    assert.equal(body.profile.roles[0]?.role, "Participant");
  });

  it("FR-33: user can login and receive JWT session", async () => {
    const email = `login+${randomUUID()}@example.com`;
    const password = "secure-pass-2";

    const registerResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: {
        email,
        password,
        displayName: "Login User",
      },
    });
    assert.equal(registerResponse.statusCode, 200, registerResponse.body);

    const loginResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/login`,
      payload: { email, password },
    });
    assert.equal(loginResponse.statusCode, 200, loginResponse.body);

    const session = JSON.parse(loginResponse.body) as {
      token: string;
      profile: { email: string; roles: Array<{ role: string }> };
    };
    assert.ok(session.token);
    assert.equal(session.profile.email, email);

    const meResponse = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/me`,
      headers: { authorization: `Bearer ${session.token}` },
    });
    assert.equal(meResponse.statusCode, 200, meResponse.body);
    const me = JSON.parse(meResponse.body) as {
      email: string;
      userId: string;
      role: string;
    };
    assert.equal(me.email, email);
    assert.equal(me.role, "Participant");
  });

  it("NFR-17: rejects duplicate email registration", async () => {
    const email = `duplicate+${randomUUID()}@example.com`;
    const payload = {
      email,
      password: "secure-pass-3",
      displayName: "Duplicate User",
    };

    const first = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload,
    });
    assert.equal(first.statusCode, 200, first.body);

    const second = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload,
    });
    assert.equal(second.statusCode, 409);
    assert.equal(parseError(second.body).error.code, "EMAIL_ALREADY_REGISTERED");
  });

  it("NFR-07: rejects invalid login credentials", async () => {
    const response = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/login`,
      payload: {
        email: "missing-user@example.com",
        password: "wrong-password",
      },
    });
    assert.equal(response.statusCode, 401);
    assert.equal(parseError(response.body).error.code, "INVALID_CREDENTIALS");
  });

  it("FR-34: sign-out is client-side; protected routes reject cleared sessions", async () => {
    const email = `signout+${randomUUID()}@example.com`;
    const password = "secure-pass-4";

    const loginResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: {
        email,
        password,
        displayName: "Sign Out User",
      },
    });
    assert.equal(loginResponse.statusCode, 200, loginResponse.body);

    const withoutToken = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/me`,
    });
    assert.equal(withoutToken.statusCode, 401);
    assert.equal(parseError(withoutToken.body).error.code, "UNAUTHENTICATED");
  });

  it("credential JWT sub maps to users.id for registration participant_id", async () => {
    const email = `mapping+${randomUUID()}@example.com`;
    const password = "secure-pass-5";

    const registerResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: {
        email,
        password,
        displayName: "Mapped User",
      },
    });
    assert.equal(registerResponse.statusCode, 200, registerResponse.body);

    const session = JSON.parse(registerResponse.body) as {
      token: string;
      profile: { userId: string };
    };

    const meResponse = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/me`,
      headers: { authorization: `Bearer ${session.token}` },
    });
    assert.equal(meResponse.statusCode, 200, meResponse.body);
    const me = JSON.parse(meResponse.body) as { userId: string; actorId: string };
    assert.equal(me.actorId, session.profile.userId);
    assert.equal(me.userId, session.profile.userId);
  });

  it("dev token route remains available when DEV_AUTH_ENABLED=true", async () => {
    const response = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/dev/token`,
      payload: {
        sub: randomUUID(),
        role: "Participant",
      },
    });
    assert.equal(response.statusCode, 200, response.body);
  });

  it("dev token route is unavailable when DEV_AUTH_ENABLED=false", async () => {
    const previous = process.env.DEV_AUTH_ENABLED;
    process.env.DEV_AUTH_ENABLED = "false";

    const { app: restrictedApp } = await buildApp();
    try {
      const response = await restrictedApp.inject({
        method: "POST",
        url: `${API_BASE_PATH}/dev/token`,
        payload: {
          sub: randomUUID(),
          role: "Participant",
        },
      });
      assert.equal(response.statusCode, 404);
    } finally {
      process.env.DEV_AUTH_ENABLED = previous;
      await restrictedApp.close();
    }
  });
});
