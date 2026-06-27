import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import fjwt from "@fastify/jwt";
import Fastify, { type FastifyInstance } from "fastify";

import { ApiError } from "../errors/api-error.js";
import {
  requireAuth,
  requireCapability,
  requireRole,
} from "./middleware.js";
import type { ActorRole, JwtPayload } from "./types.js";

async function buildMiddlewareApp(): Promise<FastifyInstance> {
  const app = Fastify();
  await app.register(fjwt, { secret: "middleware-test-secret" });

  app.get(
    "/protected",
    { onRequest: requireAuth },
    async () => ({ ok: true }),
  );

  app.get(
    "/admin-only",
    { onRequest: [requireAuth, requireRole("OrganizerAdmin")] },
    async () => ({ ok: true, role: "OrganizerAdmin" }),
  );

  app.get(
    "/create-event",
    { onRequest: [requireAuth, requireCapability("event.create")] },
    async () => ({ ok: true }),
  );

  app.setErrorHandler((error, _request, reply) => {
    if (error instanceof ApiError) {
      reply.status(error.statusCode).send({
        error: {
          code: error.code,
          message: error.message,
          details: error.details,
        },
      });
      return;
    }
    reply.status(500).send({ error: { code: "INTERNAL_ERROR" } });
  });

  return app;
}

async function signToken(
  app: FastifyInstance,
  payload: JwtPayload,
): Promise<string> {
  return app.jwt.sign(payload);
}

describe("auth middleware (FR-25)", () => {
  let app: FastifyInstance;

  before(async () => {
    app = await buildMiddlewareApp();
  });

  after(async () => {
    await app.close();
  });

  it("requireAuth rejects unauthenticated requests", async () => {
    const response = await app.inject({ method: "GET", url: "/protected" });
    assert.equal(response.statusCode, 401);
    assert.equal(
      JSON.parse(response.body).error.code,
      "UNAUTHENTICATED",
    );
  });

  it("requireRole allows OrganizerAdmin on admin-only route", async () => {
    const token = await signToken(app, {
      sub: "00000000-0000-0000-0000-000000000099",
      role: "OrganizerAdmin",
    });

    const response = await app.inject({
      method: "GET",
      url: "/admin-only",
      headers: { authorization: `Bearer ${token}` },
    });

    assert.equal(response.statusCode, 200);
    assert.equal(JSON.parse(response.body).role, "OrganizerAdmin");
  });

  it("requireRole denies Participant and OrganizerStaff", async () => {
    for (const role of ["Participant", "OrganizerStaff"] as ActorRole[]) {
      const token = await signToken(app, {
        sub: `actor-${role}`,
        role,
        assignedEventIds: [],
      });

      const response = await app.inject({
        method: "GET",
        url: "/admin-only",
        headers: { authorization: `Bearer ${token}` },
      });

      assert.equal(response.statusCode, 403, role);
      assert.equal(JSON.parse(response.body).error.code, "FORBIDDEN");
    }
  });

  it("requireCapability enforces permission matrix for event.create", async () => {
    const adminToken = await signToken(app, {
      sub: "admin-1",
      role: "OrganizerAdmin",
    });
    const allowed = await app.inject({
      method: "GET",
      url: "/create-event",
      headers: { authorization: `Bearer ${adminToken}` },
    });
    assert.equal(allowed.statusCode, 200);

    const participantToken = await signToken(app, {
      sub: "participant-1",
      role: "Participant",
    });
    const denied = await app.inject({
      method: "GET",
      url: "/create-event",
      headers: { authorization: `Bearer ${participantToken}` },
    });
    assert.equal(denied.statusCode, 403);
    assert.equal(JSON.parse(denied.body).error.code, "FORBIDDEN");
  });
});
