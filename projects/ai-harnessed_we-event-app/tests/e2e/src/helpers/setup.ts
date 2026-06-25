import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { buildApp } from "../../../../apps/api/src/index.js";

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
  const response = await app.inject({
    method: "POST",
    url: `${API_PREFIX}/dev/token`,
    payload: { sub, role, assignedEventIds },
  });
  assert.equal(response.statusCode, 200, response.body);
  return (JSON.parse(response.body) as { token: string }).token;
}

export async function apiRequest(
  app: FastifyInstance,
  options: {
    method: "GET" | "POST" | "PATCH";
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
