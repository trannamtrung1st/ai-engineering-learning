import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { SESSION_COOKIE_NAME, UserRole } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import {
  createAuthMiddleware,
  extractSessionId,
  requirePermission,
} from "../../auth/middleware.js";
import { Permission } from "../../auth/permissions.js";
import type { SessionStore } from "../../auth/session-store.js";
import { validationFailed, forbidden, notFound } from "../../errors/api-error.js";
import { AuthService } from "./auth-service.js";
import { PolicyService } from "./policy-service.js";
import { UserRepository } from "./user-repository.js";
import { UserService } from "./user-service.js";
import {
  validateCreateUserBody,
  validateListUsersQuery,
  validateLoginBody,
  validateSessionInactivityHours,
  validateUpdateUserBody,
} from "./validation.js";

function requireAdmin(request: FastifyRequest): void {
  if (request.auth?.user.role !== UserRole.TrainingOfficeAdmin) {
    throw forbidden();
  }
}

function setSessionCookie(
  reply: FastifyReply,
  sessionId: string,
  secure: boolean,
): void {
  void reply.setCookie(SESSION_COOKIE_NAME, sessionId, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
  });
}

function clearSessionCookie(reply: FastifyReply): void {
  void reply.clearCookie(SESSION_COOKIE_NAME, { path: "/" });
}

export async function registerIdentityAuthRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
): Promise<void> {
  const users = new UserRepository(db);
  const authService = new AuthService(users, store);
  const userService = new UserService(users, store);
  const policyService = new PolicyService(db);
  const auth = createAuthMiddleware(store);
  const secureCookies = process.env.NODE_ENV === "production";

  app.post("/auth/login", async (request, reply) => {
    const parsed = validateLoginBody(request.body);
    if (!parsed.ok) {
      throw validationFailed(parsed.details);
    }

    const result = await authService.authenticate(parsed.value);
    setSessionCookie(reply, result.session.id, secureCookies);

    return {
      user: {
        id: result.user.id,
        institutionalId: result.user.institutionalId,
        displayName: result.user.displayName,
        email: result.user.email,
        role: result.user.role,
      },
      session: {
        id: result.session.id,
        expiresAt: result.session.expiresAt.toISOString(),
      },
      ...(result.redirectTo ? { redirectTo: result.redirectTo } : {}),
    };
  });

  app.post(
    "/auth/logout",
    { preHandler: [auth] },
    async (request, reply) => {
      const sessionId = extractSessionId(request);
      if (sessionId) {
        await authService.logout(sessionId);
      }
      clearSessionCookie(reply);
      return reply.status(204).send();
    },
  );

  app.get(
    "/auth/me",
    { preHandler: [auth, requirePermission(Permission.UserRead)] },
    async (request) => {
      const { user } = request.auth!;
      return {
        id: user.id,
        institutionalId: user.institutionalId,
        displayName: user.displayName,
        email: user.email,
        role: user.role,
      };
    },
  );

  const seedEnabled =
    process.env.SEED_ENABLED === "true" || process.env.SEED_ENABLED === "1";

  if (seedEnabled) {
    /** Preview-only: backdate current session for AC-02c browser gate (TC-AC-02-013) */
    app.post(
      "/auth/preview/expire-session",
      { preHandler: [auth] },
      async (request) => {
        const sessionId = extractSessionId(request);
        if (!sessionId) {
          throw notFound();
        }
        await db.query(
          `UPDATE auth_sessions
           SET last_activity_at = NOW() - INTERVAL '9 hours',
               expires_at = NOW() - INTERVAL '1 hour'
           WHERE id = $1 AND revoked_at IS NULL`,
          [sessionId],
        );
        return { ok: true };
      },
    );
  }

  app.get(
    "/users",
    { preHandler: [auth, requirePermission(Permission.UserRead)] },
    async (request) => {
      requireAdmin(request);
      const query = request.query as Record<string, unknown>;
      const parsed = validateListUsersQuery(query);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }
      return userService.list(parsed.value);
    },
  );

  app.post(
    "/users",
    { preHandler: [auth, requirePermission(Permission.UserWrite)] },
    async (request, reply) => {
      const parsed = validateCreateUserBody(request.body);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }
      const user = await userService.provision(parsed.value);
      return reply.status(201).send(user);
    },
  );

  app.patch(
    "/users/:userId",
    { preHandler: [auth, requirePermission(Permission.UserWrite)] },
    async (request) => {
      const parsed = validateUpdateUserBody(request.body);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }
      const { userId } = request.params as { userId: string };
      const actorId = request.auth!.user.id;
      return userService.update(userId, parsed.value, actorId);
    },
  );

  app.get(
    "/policy/session-inactivity",
    { preHandler: [auth, requirePermission(Permission.PolicyWrite)] },
    async () => {
      const inactivityHours = await policyService.getSessionInactivityHours();
      return { inactivityHours };
    },
  );

  app.put(
    "/policy/session-inactivity",
    { preHandler: [auth, requirePermission(Permission.PolicyWrite)] },
    async (request) => {
      const parsed = validateSessionInactivityHours(request.body);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }
      const adminId = request.auth!.user.id;
      const inactivityHours = await policyService.setSessionInactivityHours(
        parsed.value.inactivityHours,
        adminId,
      );
      return { inactivityHours };
    },
  );
}
