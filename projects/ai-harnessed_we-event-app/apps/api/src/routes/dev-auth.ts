import { ACTOR_ROLES } from "@we-event/domain";
import type { FastifyPluginAsync } from "fastify";
import type { AppConfig } from "../config.js";
import { resolveActorId } from "../auth/resolve-actor-id.js";
import type { ActorRole } from "../auth/types.js";
import { buildErrorEnvelope } from "../errors/api-error.js";
import { ensureParticipantAccount } from "../modules/user/repository.js";

interface DevTokenBody {
  sub: string;
  role: ActorRole;
  assignedEventIds?: string[];
}

export function devAuthRoutes(config: AppConfig): FastifyPluginAsync {
  return async (app) => {
    if (!config.devAuthEnabled) {
      return;
    }

    app.post<{ Body: DevTokenBody }>("/dev/token", async (request, reply) => {
      const { sub, role, assignedEventIds } = request.body ?? {};

      if (!sub || typeof sub !== "string") {
        return reply
          .status(400)
          .send(
            buildErrorEnvelope(
              "INVALID_INPUT",
              "sub is required.",
              request.id,
            ),
          );
      }

      if (!role || !ACTOR_ROLES.includes(role)) {
        return reply.status(400).send(
          buildErrorEnvelope(
            "INVALID_INPUT",
            `role must be one of: ${ACTOR_ROLES.join(", ")}.`,
            request.id,
            { allowedRoles: ACTOR_ROLES },
          ),
        );
      }

      if (role === "Participant") {
        await ensureParticipantAccount(resolveActorId(sub));
      }

      const token = await reply.jwtSign({
        sub,
        role,
        assignedEventIds: assignedEventIds ?? [],
      });

      return { token, sub, role, assignedEventIds: assignedEventIds ?? [] };
    });
  };
}
