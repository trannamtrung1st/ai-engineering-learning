import type { FastifyPluginAsync } from "fastify";
import { getActor } from "../auth/middleware.js";
import { resolveActorId } from "../auth/resolve-actor-id.js";
import {
  findUserById,
  listUserRoles,
  toUserProfile,
} from "../modules/user/repository.js";

export const sessionRoutes: FastifyPluginAsync = async (app) => {
  app.get("/me", async (request) => {
    const actor = getActor(request);
    const user = await findUserById(resolveActorId(actor.sub));

    if (user) {
      const roles = await listUserRoles(user.id);
      return {
        ...toUserProfile(user, roles),
        actorId: actor.sub,
        role: actor.role,
        assignedEventIds: actor.assignedEventIds ?? [],
      };
    }

    return {
      actorId: actor.sub,
      role: actor.role,
      assignedEventIds: actor.assignedEventIds ?? [],
    };
  });
};
