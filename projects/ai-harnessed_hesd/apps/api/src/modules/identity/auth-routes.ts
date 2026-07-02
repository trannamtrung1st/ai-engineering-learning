import bcrypt from "bcryptjs";
import type { FastifyInstance } from "fastify";
import { ErrorCode } from "@attendly/domain";
import { accessTokenExpirySeconds, signAccessToken } from "./jwt.js";
import { sendApiError, sendApiSuccess, unauthenticated } from "./http.js";
import {
  createAuthenticate,
  type IdentityServices,
} from "./middleware.js";
import type { IdentityRepository } from "./repository.js";
import { toMeResponse } from "./repository.js";

export interface AuthRouteDeps {
  repository: IdentityRepository;
}

export async function registerAuthRoutes(
  app: FastifyInstance,
  deps: AuthRouteDeps,
): Promise<void> {
  const services: IdentityServices = { repository: deps.repository };
  const authenticate = createAuthenticate(services);

  app.post("/auth/login", async (request, reply) => {
    const body = request.body as { email?: string; password?: string } | undefined;
    const email = body?.email?.trim();
    const password = body?.password;

    if (!email || !password) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    const user = await deps.repository.findUserByEmail(email);
    if (!user?.password_hash) {
      sendApiError(reply, request, 401, ErrorCode.Unauthenticated);
      return;
    }

    const valid = await bcrypt.compare(password, user.password_hash);
    if (!valid) {
      sendApiError(reply, request, 401, ErrorCode.Unauthenticated);
      return;
    }

    const assignments = await deps.repository.getRoleAssignments(user.id);
    const roles = [...new Set(assignments.map((a) => a.role))];
    const accessToken = await signAccessToken({
      sub: user.id,
      email: user.email,
      roles,
    });

    sendApiSuccess(reply, request, 200, {
      accessToken,
      expiresInSeconds: accessTokenExpirySeconds(),
      roles,
    });
  });

  app.get(
    "/me",
    {
      preHandler: authenticate,
    },
    async (request, reply) => {
      if (!request.actor) {
        unauthenticated(reply, request);
        return;
      }

      const facultyIds = request.actor.assignments
        .filter((a) => a.scopeType === "Faculty" && a.scopeId)
        .map((a) => a.scopeId as string);

      const classSectionIds = [
        ...(await deps.repository.getLecturerClassSectionIds(request.actor.userId)),
        ...request.actor.assignments
          .filter((a) => a.scopeType === "ClassSection" && a.scopeId)
          .map((a) => a.scopeId as string),
      ];

      sendApiSuccess(
        reply,
        request,
        200,
        toMeResponse(request.actor, {
          facultyIds: [...new Set(facultyIds)],
          classSectionIds: [...new Set(classSectionIds)],
        }),
      );
    },
  );
}
