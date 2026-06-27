import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { buildApp } from "../../../../apps/api/src/index.js";
import { resolveActorId } from "../../../../apps/api/src/auth/resolve-actor-id.js";
import {
  ensureTestOrganizerAdmin,
  ensureTestParticipant,
  ensureTestUser,
} from "../../../../apps/api/src/test-helpers/participant-user.js";

const API_PREFIX = "/api/v1";

type DevActorRole = "Participant" | "OrganizerAdmin" | "OrganizerStaff";

export const DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001";
export const ORGANIZER_ADMIN_SUB = "00000000-0000-0000-0000-000000000099";

export interface PaginatedEnvelope<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
  };
}

export interface E2EContext {
  app: FastifyInstance;
}

export function defaultTimeWindows() {
  const now = Date.now();
  return {
    open: new Date(now - 3_600_000).toISOString(),
    close: new Date(now + 86_400_000).toISOString(),
  };
}

export function futureWindow(offsetMs: number) {
  const start = Date.now() + offsetMs;
  return {
    open: new Date(start).toISOString(),
    close: new Date(start + 86_400_000).toISOString(),
  };
}

export async function createE2EContext(): Promise<E2EContext> {
  process.env.DATABASE_URL ??=
    "postgresql://we_event:we_event@localhost:5432/we_event";
  process.env.JWT_SECRET ??= "e2e-jwt-secret";
  process.env.DEV_AUTH_ENABLED = "true";

  const { app } = await buildApp();
  await ensureTestOrganizerAdmin(ORGANIZER_ADMIN_SUB);
  return { app };
}

export async function destroyE2EContext(ctx: E2EContext): Promise<void> {
  await ctx.app.close();
}

export async function signDevToken(
  app: FastifyInstance,
  sub: string,
  role: DevActorRole,
  assignedEventIds?: string[],
): Promise<string> {
  const userId = resolveActorId(sub);
  if (role === "Participant") {
    await ensureTestParticipant(userId);
  } else if (role === "OrganizerAdmin") {
    await ensureTestOrganizerAdmin(userId);
  } else {
    await ensureTestUser(userId, role, {
      assignedEventIds: assignedEventIds ?? [],
    });
  }

  const response = await app.inject({
    method: "POST",
    url: `${API_PREFIX}/dev/token`,
    payload: { sub, role, assignedEventIds },
  });
  assert.equal(response.statusCode, 200, response.body);
  return (JSON.parse(response.body) as { token: string }).token;
}

export function buildMultipartPayload(
  boundary: string,
  filename: string,
  mimeType: string,
  data: Buffer,
): Buffer {
  const prefix = Buffer.from(
    `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="file"; filename="${filename}"\r\n` +
      `Content-Type: ${mimeType}\r\n\r\n`,
  );
  const suffix = Buffer.from(`\r\n--${boundary}--\r\n`);
  return Buffer.concat([prefix, data, suffix]);
}

export async function uploadCoverImage(
  app: FastifyInstance,
  options: {
    eventId: string;
    token: string;
    filename: string;
    mimeType: string;
    data: Buffer;
    boundary?: string;
  },
) {
  const boundary = options.boundary ?? `we-event-cover-${randomUUID()}`;
  return app.inject({
    method: "POST",
    url: `${API_PREFIX}/events/${options.eventId}/cover-image`,
    headers: {
      authorization: `Bearer ${options.token}`,
      "content-type": `multipart/form-data; boundary=${boundary}`,
    },
    payload: buildMultipartPayload(
      boundary,
      options.filename,
      options.mimeType,
      options.data,
    ),
  });
}

export async function apiRequest(
  app: FastifyInstance,
  options: {
    method: "GET" | "POST" | "PATCH" | "DELETE";
    path: string;
    token?: string;
    payload?: unknown;
    idempotencyKey?: string;
  },
) {
  const headers: Record<string, string> = {};
  if (options.token) {
    headers.authorization = `Bearer ${options.token}`;
  }
  if (options.idempotencyKey) {
    headers["idempotency-key"] = options.idempotencyKey;
  }
  if (options.payload !== undefined) {
    headers["content-type"] = "application/json";
  }

  return app.inject({
    method: options.method,
    url: `${API_PREFIX}${options.path}`,
    headers,
    payload: options.payload,
  });
}

export function parseJson<T>(body: string): T {
  return JSON.parse(body) as T;
}

export function assertOk(statusCode: number, body: string, context: string): void {
  assert.equal(statusCode, 200, `${context}: ${body}`);
}

export function newParticipantSub(): string {
  return randomUUID();
}

export function newIdempotencyKey(): string {
  return randomUUID();
}
