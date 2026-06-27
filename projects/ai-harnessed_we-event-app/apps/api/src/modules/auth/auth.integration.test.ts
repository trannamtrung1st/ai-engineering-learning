import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import type { FastifyInstance } from "fastify";

import { API_BASE_PATH, buildApp } from "../../index.js";
import { closeDb, getPool } from "../../db/pool.js";
import { ensureUserSchema } from "../user/repository.js";
import { ensureTestOrganizerAdmin } from "../../test-helpers/participant-user.js";
import type { JwtPayload } from "../../auth/types.js";

function parseError(body: string) {
  return JSON.parse(body) as {
    error: { code: string; message: string };
  };
}

function decodeJwtPayload(token: string): JwtPayload {
  const payload = token.split(".")[1];
  assert.ok(payload);
  return JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as JwtPayload;
}

function assertNoCredentialSecrets(body: string): void {
  assert.doesNotMatch(body, /passwordHash|"password"\s*:/i);
  assert.doesNotMatch(body, /\$2[aby]\$/);
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

  it("TC-FR-32-002: registration persists normalized lowercase email", async () => {
    const mixedCaseEmail = `MixedCase+${randomUUID()}@Example.COM`;
    const password = "secure-pass-norm";

    const response = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: {
        email: mixedCaseEmail,
        password,
        displayName: "  Normalized User  ",
      },
    });
    assert.equal(response.statusCode, 200, response.body);

    const normalized = mixedCaseEmail.trim().toLowerCase();
    const row = await getPool().query(
      `SELECT email, display_name FROM users WHERE lower(email) = lower($1)`,
      [normalized],
    );
    assert.equal(row.rowCount, 1);
    assert.equal(row.rows[0]!.email, normalized);
    assert.equal(row.rows[0]!.display_name, "Normalized User");
  });

  it("TC-FR-32-005 / NFR-08-014: signup assigns Participant role only", async () => {
    const email = `participant-only+${randomUUID()}@example.com`;
    const password = "secure-pass-role";

    const registerResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: {
        email,
        password,
        displayName: "Participant Only",
      },
    });
    assert.equal(registerResponse.statusCode, 200, registerResponse.body);
    assertNoCredentialSecrets(registerResponse.body);

    const session = JSON.parse(registerResponse.body) as {
      token: string;
      profile: { roles: Array<{ role: string }> };
    };
    assert.equal(session.profile.roles.length, 1);
    assert.equal(session.profile.roles[0]?.role, "Participant");

    const createEventResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events`,
      headers: { authorization: `Bearer ${session.token}` },
      payload: {
        name: "Blocked Event",
        organizationId: "00000000-0000-0000-0000-000000000001",
        startAt: "2026-12-01T09:00:00.000Z",
        endAt: "2026-12-01T17:00:00.000Z",
        location: "Room A",
      },
    });
    assert.equal(createEventResponse.statusCode, 403);
    assert.equal(parseError(createEventResponse.body).error.code, "FORBIDDEN");
  });

  it("TC-NFR-17-003 / TC-FR-32-007: signup stores bcrypt adaptive hash", async () => {
    const email = `hash+${randomUUID()}@example.com`;
    const password = "known-password-1";

    const response = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: {
        email,
        password,
        displayName: "Hash User",
      },
    });
    assert.equal(response.statusCode, 200, response.body);

    const row = await getPool().query(
      `SELECT password_hash FROM users WHERE lower(email) = lower($1)`,
      [email],
    );
    const hash = row.rows[0]!.password_hash as string;
    assert.match(hash, /^\$2[aby]\$/);
    assert.notEqual(hash, password);
  });

  it("TC-NFR-17-005: GET /me excludes password hash from profile", async () => {
    const email = `me-secrets+${randomUUID()}@example.com`;
    const password = "secure-pass-me";

    const registerResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: { email, password, displayName: "Me Secrets User" },
    });
    assert.equal(registerResponse.statusCode, 200, registerResponse.body);
    const { token } = JSON.parse(registerResponse.body) as { token: string };

    const meResponse = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/me`,
      headers: { authorization: `Bearer ${token}` },
    });
    assert.equal(meResponse.statusCode, 200, meResponse.body);
    assertNoCredentialSecrets(meResponse.body);
  });

  it("TC-NFR-17-010: identical passwords produce distinct password_hash values", async () => {
    const password = "shared-password-1";
    const emailA = `hash-a+${randomUUID()}@example.com`;
    const emailB = `hash-b+${randomUUID()}@example.com`;

    for (const email of [emailA, emailB]) {
      const response = await app.inject({
        method: "POST",
        url: `${API_BASE_PATH}/auth/register`,
        payload: { email, password, displayName: "Shared Password User" },
      });
      assert.equal(response.statusCode, 200, response.body);
    }

    const hashes = await getPool().query(
      `SELECT password_hash FROM users WHERE lower(email) = ANY($1::text[])`,
      [[emailA.toLowerCase(), emailB.toLowerCase()]],
    );
    assert.equal(hashes.rowCount, 2);
    const [first, second] = hashes.rows.map((row) => row.password_hash as string);
    assert.notEqual(first, second);
    assert.notEqual(first, password);
    assert.notEqual(second, password);
  });

  it("TC-NFR-17-011: login rejects wrong password for existing account", async () => {
    const email = `wrong-pass+${randomUUID()}@example.com`;
    const password = "correct-password";

    const registerResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: { email, password, displayName: "Wrong Pass User" },
    });
    assert.equal(registerResponse.statusCode, 200, registerResponse.body);

    const loginResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/login`,
      payload: { email, password: "incorrect-password" },
    });
    assert.equal(loginResponse.statusCode, 401);
    assert.equal(parseError(loginResponse.body).error.code, "INVALID_CREDENTIALS");
    assertNoCredentialSecrets(loginResponse.body);
  });

  it("TC-FR-33-005 / TC-FR-33-006: login JWT sub equals users.id and profile roles", async () => {
    const email = `jwt-sub+${randomUUID()}@example.com`;
    const password = "secure-pass-jwt";

    const registerResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: { email, password, displayName: "JWT Sub User" },
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
      profile: { userId: string; roles: Array<{ role: string }> };
    };
    const payload = decodeJwtPayload(session.token);
    assert.equal(payload.sub, session.profile.userId);
    assert.equal(session.profile.roles[0]?.role, "Participant");

    const meResponse = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/me`,
      headers: { authorization: `Bearer ${session.token}` },
    });
    assert.equal(meResponse.statusCode, 200, meResponse.body);
    const me = JSON.parse(meResponse.body) as {
      userId: string;
      roles: Array<{ role: string }>;
    };
    assert.equal(me.userId, session.profile.userId);
    assert.equal(me.roles[0]?.role, "Participant");
  });

  it("TC-FR-34-006: omitted bearer after sign-out matches unauthenticated rejection", async () => {
    const email = `signout-sim+${randomUUID()}@example.com`;
    const password = "secure-pass-signout";

    const loginResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/auth/register`,
      payload: { email, password, displayName: "Signout Sim User" },
    });
    assert.equal(loginResponse.statusCode, 200, loginResponse.body);
    const { token } = JSON.parse(loginResponse.body) as { token: string };

    const authenticated = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/me`,
      headers: { authorization: `Bearer ${token}` },
    });
    assert.equal(authenticated.statusCode, 200, authenticated.body);

    const signedOut = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/me`,
    });
    assert.equal(signedOut.statusCode, 401);
    assert.equal(parseError(signedOut.body).error.code, "UNAUTHENTICATED");

    const neverAuthenticated = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/me`,
    });
    assert.equal(neverAuthenticated.statusCode, 401);
    assert.equal(parseError(neverAuthenticated.body).error.code, "UNAUTHENTICATED");
  });

  it("TC-FR-32-014: mixed-case duplicate email rejected on register", async () => {
    const email = `case-dup+${randomUUID()}@example.com`;
    const payload = {
      email,
      password: "secure-pass-dup",
      displayName: "Case Dup User",
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
      payload: {
        ...payload,
        email: email.toUpperCase(),
        displayName: "Other Name",
      },
    });
    assert.equal(second.statusCode, 409);
    assert.equal(parseError(second.body).error.code, "EMAIL_ALREADY_REGISTERED");
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
