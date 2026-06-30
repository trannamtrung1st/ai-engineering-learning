import type { FastifyInstance, FastifyReply } from "fastify";
import { SESSION_COOKIE_NAME } from "@wecheck/domain";
import type { DbPool } from "../../../infra/db.js";
import type { SessionStore } from "../../../auth/session-store.js";
import { validationFailed } from "../../../errors/api-error.js";
import { UserRepository } from "../user-repository.js";
import { validateFirstAdminBody } from "../validation.js";
import { SetupService } from "./setup-service.js";

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

export async function registerSetupRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
): Promise<void> {
  const users = new UserRepository(db);
  const setupService = new SetupService(db, users, store);
  const secureCookies = process.env.NODE_ENV === "production";

  app.get("/setup/status", async () => {
    return setupService.getStatus();
  });

  app.post("/setup/first-admin", async (request, reply) => {
    const parsed = validateFirstAdminBody(request.body);
    if (!parsed.ok) {
      throw validationFailed(parsed.details);
    }

    const result = await setupService.createFirstAdmin(parsed.value);
    setSessionCookie(reply, result.session.id, secureCookies);

    return reply.status(201).send({
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
    });
  });
}
