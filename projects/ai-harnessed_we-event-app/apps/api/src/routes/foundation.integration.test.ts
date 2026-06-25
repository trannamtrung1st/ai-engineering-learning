import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import type { FastifyInstance } from "fastify";

import { API_BASE_PATH, buildApp } from "../index.js";
import { resolveActorId } from "../auth/resolve-actor-id.js";

async function signDevToken(
  app: FastifyInstance,
  sub: string,
  role: string,
  assignedEventIds: string[] = [],
): Promise<string> {
  const response = await app.inject({
    method: "POST",
    url: `${API_BASE_PATH}/dev/token`,
    payload: { sub, role, assignedEventIds },
  });
  assert.equal(response.statusCode, 200, response.body);
  return (JSON.parse(response.body) as { token: string }).token;
}

function parseError(body: string) {
  return JSON.parse(body) as {
    error: {
      code: string;
      message: string;
      requestId: string;
      timestamp: string;
      details: Record<string, unknown>;
    };
  };
}

describe("api foundation", () => {
  let app: FastifyInstance;

  before(async () => {
    process.env.DATABASE_URL ??=
      "postgresql://we_event:we_event@localhost:5432/we_event";
    process.env.JWT_SECRET ??= "test-jwt-secret";
    process.env.DEV_AUTH_ENABLED = "true";

    ({ app } = await buildApp());
  });

  after(async () => {
    await app.close();
  });

  it("exposes versioned base path /api/v1", async () => {
    const response = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/health`,
    });

    assert.equal(response.statusCode, 200);
    const body = JSON.parse(response.body) as {
      status: string;
      db: string;
      requestId: string;
    };
    assert.equal(body.status, "ok");
    assert.equal(body.db, "connected");
    assert.match(body.requestId, /^[0-9a-f-]{36}$/i);
  });

  it("returns error envelope for unauthenticated protected routes", async () => {
    const response = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/me`,
    });

    assert.equal(response.statusCode, 401);
    const { error } = parseError(response.body);
    assert.equal(error.code, "UNAUTHENTICATED");
    assert.equal(error.message, "Authentication required.");
    assert.match(error.requestId, /^[0-9a-f-]{36}$/i);
    assert.match(error.timestamp, /^\d{4}-\d{2}-\d{2}T/);
  });

  it("FR-25: enforces role-based access on protected admin routes", async () => {
    const participantToken = await signDevToken(app, "participant-1", "Participant");
    const adminToken = await signDevToken(
      app,
      "00000000-0000-0000-0000-000000000099",
      "OrganizerAdmin",
    );

    const denied = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/admin/status`,
      headers: { authorization: `Bearer ${participantToken}` },
    });
    assert.equal(denied.statusCode, 403);
    assert.equal(parseError(denied.body).error.code, "FORBIDDEN");

    const allowed = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/admin/status`,
      headers: { authorization: `Bearer ${adminToken}` },
    });
    assert.equal(allowed.statusCode, 200);
    const body = JSON.parse(allowed.body) as { status: string; role: string };
    assert.equal(body.status, "ok");
    assert.equal(body.role, "OrganizerAdmin");
  });

  it("FR-26: participant can only access own registration scope", async () => {
    const ownSub = "participant-scope-a";
    const otherSub = "participant-scope-b";
    const token = await signDevToken(app, ownSub, "Participant");

    const ownResponse = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/participants/${resolveActorId(ownSub)}/access`,
      headers: { authorization: `Bearer ${token}` },
    });
    assert.equal(ownResponse.statusCode, 200);

    const otherResponse = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/participants/${resolveActorId(otherSub)}/access`,
      headers: { authorization: `Bearer ${token}` },
    });
    assert.equal(otherResponse.statusCode, 403);
    assert.equal(parseError(otherResponse.body).error.code, "FORBIDDEN");
  });
});
