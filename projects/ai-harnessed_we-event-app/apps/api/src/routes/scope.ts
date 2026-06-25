import type { FastifyPluginAsync } from "fastify";
import { getActor } from "../auth/middleware.js";
import { assertEventScope, assertParticipantOwnership } from "../auth/scope.js";

export const scopeRoutes: FastifyPluginAsync = async (app) => {
  app.get<{ Params: { participantId: string } }>(
    "/participants/:participantId/access",
    async (request) => {
      const actor = getActor(request);
      const { participantId } = request.params;
      assertParticipantOwnership(actor, participantId);

      return {
        allowed: true,
        actorId: actor.sub,
        participantId,
        role: actor.role,
      };
    },
  );

  app.get<{ Params: { eventId: string } }>(
    "/events/:eventId/access",
    async (request) => {
      const actor = getActor(request);
      const { eventId } = request.params;
      assertEventScope(actor, eventId);

      return {
        allowed: true,
        actorId: actor.sub,
        eventId,
        role: actor.role,
      };
    },
  );
};
