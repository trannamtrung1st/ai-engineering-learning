import type { FastifyPluginAsync } from "fastify";
import { getActor } from "../auth/middleware.js";
import {
  assertEventScope,
  assertParticipantOwnership,
  assertRegistrationScope,
} from "../auth/scope.js";

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

  app.get<{
    Params: { registrationId: string };
    Querystring: { participantId: string };
  }>("/registrations/:registrationId/access", async (request) => {
    const actor = getActor(request);
    const { registrationId } = request.params;
    const { participantId } = request.query;
    assertRegistrationScope(actor, registrationId, participantId);

    return {
      allowed: true,
      actorId: actor.sub,
      registrationId,
      participantId,
      role: actor.role,
    };
  });

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
