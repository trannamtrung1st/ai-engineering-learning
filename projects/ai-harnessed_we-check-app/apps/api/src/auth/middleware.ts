import type { FastifyReply, FastifyRequest } from "fastify";
import { SESSION_COOKIE_NAME } from "@wecheck/domain";
import { ApiError, sessionExpired, unauthenticated } from "../errors/api-error.js";
import type { SessionStore } from "./session-store.js";
import type { Permission } from "./permissions.js";
import { assertPermission } from "./permissions.js";
import { exportNotAllowed, forbidden, reportAccessDenied } from "../errors/api-error.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function extractSessionId(request: FastifyRequest): string | null {
  const cookieSession = request.cookies?.[SESSION_COOKIE_NAME];
  if (cookieSession && UUID_RE.test(cookieSession)) {
    return cookieSession;
  }

  const authHeader = request.headers.authorization;
  if (authHeader?.startsWith("Bearer ")) {
    const token = authHeader.slice("Bearer ".length).trim();
    if (UUID_RE.test(token)) {
      return token;
    }
  }

  return null;
}

export function createAuthMiddleware(store: SessionStore) {
  return async function authMiddleware(request: FastifyRequest): Promise<void> {
    const sessionId = extractSessionId(request);
    if (!sessionId) {
      throw unauthenticated();
    }

    const resolved = await store.resolveSession(sessionId);
    if (!resolved.ok) {
      if (resolved.reason === "expired") {
        throw sessionExpired();
      }
      throw unauthenticated();
    }

    await store.touchSession(sessionId);
    request.auth = {
      session: resolved.session,
      user: resolved.user,
    };
  };
}

export function requirePermission(
  permission: Permission,
  options?: { reportAccess?: boolean; exportAccess?: boolean },
) {
  return async function permissionGuard(request: FastifyRequest): Promise<void> {
    if (!request.auth) {
      throw unauthenticated();
    }

    const { role } = request.auth.user;
    if (!assertPermission(role, permission)) {
      if (options?.exportAccess) {
        throw exportNotAllowed();
      }
      if (options?.reportAccess) {
        throw reportAccessDenied();
      }
      throw forbidden();
    }
  };
}

export function optionalAuth(store: SessionStore) {
  return async function optionalAuthMiddleware(
    request: FastifyRequest,
  ): Promise<void> {
    const sessionId = extractSessionId(request);
    if (!sessionId) {
      return;
    }

    const resolved = await store.resolveSession(sessionId);
    if (resolved.ok) {
      await store.touchSession(sessionId);
      request.auth = {
        session: resolved.session,
        user: resolved.user,
      };
    }
  };
}

export function sendApiError(
  reply: FastifyReply,
  request: FastifyRequest,
  error: ApiError,
): void {
  void reply.status(error.statusCode).send(error.toBody(request.requestId));
}
