import type { FastifyPluginAsync } from "fastify";
import {
  assertEventScope,
  assertParticipantOwnership,
} from "../../auth/scope.js";
import { getActor, requireRole } from "../../auth/middleware.js";
import { resolveActorId } from "../../auth/resolve-actor-id.js";
import { ApiError } from "../../errors/api-error.js";
import {
  ensureIdempotencySchema,
  executeIdempotent,
} from "../../idempotency/index.js";
import { ensureRegistrationSchema } from "./repository.js";
import { registrationService } from "./service.js";
import type {
  CancelInput,
  ListMyRegistrationsQuery,
  ListRegistrationsQuery,
  ListWaitlistQuery,
} from "./types.js";

interface EventParams {
  eventId: string;
}

interface RegistrationParams extends EventParams {
  registrationId: string;
}

interface RegisterBody {
  participantId?: string;
}

export const registrationRoutes: FastifyPluginAsync = async (app) => {
  await ensureRegistrationSchema();
  await ensureIdempotencySchema();

  app.get<{ Querystring: ListMyRegistrationsQuery }>(
    "/me/registrations",
    async (request) => {
      const actor = getActor(request);
      if (actor.role !== "Participant") {
        throw new ApiError({
          code: "FORBIDDEN",
          message: "Only participants can list their registrations.",
          statusCode: 403,
        });
      }

      return registrationService.listMyRegistrations(
        actor.sub,
        request.query,
      );
    },
  );

  app.get<{ Params: EventParams }>(
    "/events/:eventId/registration-status",
    async (request) => {
      const actor = getActor(request);
      const { eventId } = request.params;
      return registrationService.getStatus(eventId, actor.sub);
    },
  );

  app.post<{ Params: EventParams; Body?: RegisterBody }>(
    "/events/:eventId/registrations",
    async (request) => {
      const actor = getActor(request);
      if (actor.role !== "Participant") {
        throw new ApiError({
          code: "FORBIDDEN",
          message: "Only participants can register for events.",
          statusCode: 403,
        });
      }

      const { eventId } = request.params;
      const participantId = request.body?.participantId ?? actor.sub;
      assertParticipantOwnership(actor, participantId);
      const resolvedActorId = resolveActorId(actor.sub);
      const resolvedParticipantId = resolveActorId(participantId);

      const fingerprint = JSON.stringify({
        eventId,
        participantId: resolvedParticipantId,
      });
      return executeIdempotent(
        request.headers,
        resolvedActorId,
        `registration.register:${eventId}`,
        fingerprint,
        () =>
          registrationService.register(eventId, participantId, {
            actorId: resolvedActorId,
            actorRole: actor.role,
          }),
      );
    },
  );

  app.post<{ Params: RegistrationParams; Body?: CancelInput }>(
    "/events/:eventId/registrations/:registrationId/cancel",
    async (request) => {
      const actor = getActor(request);
      const { eventId, registrationId } = request.params;

      const resolvedActorId = resolveActorId(actor.sub);
      const cancelContext = {
        actorId: resolvedActorId,
        actorRole: actor.role,
      };
      const cancelBody = request.body;
      const asOrganizer =
        actor.role === "OrganizerAdmin" || actor.role === "OrganizerStaff";

      if (actor.role === "Participant") {
        const fingerprint = JSON.stringify({
          eventId,
          registrationId,
          body: cancelBody ?? {},
        });
        return executeIdempotent(
          request.headers,
          resolvedActorId,
          `registration.cancel:${eventId}:${registrationId}`,
          fingerprint,
          () =>
            registrationService.cancel(
              eventId,
              registrationId,
              cancelContext,
              cancelBody,
            ),
        );
      }

      if (asOrganizer) {
        assertEventScope(actor, eventId);
        const fingerprint = JSON.stringify({
          eventId,
          registrationId,
          body: cancelBody ?? {},
          asOrganizer: true,
        });
        return executeIdempotent(
          request.headers,
          resolvedActorId,
          `registration.cancel:${eventId}:${registrationId}`,
          fingerprint,
          () =>
            registrationService.cancel(
              eventId,
              registrationId,
              cancelContext,
              cancelBody,
              { asOrganizer: true },
            ),
        );
      }

      throw new ApiError({
        code: "FORBIDDEN",
        message: "You do not have permission to cancel this registration.",
        statusCode: 403,
      });
    },
  );

  app.register(async (staffApp) => {
    staffApp.addHook(
      "onRequest",
      requireRole("OrganizerAdmin", "OrganizerStaff"),
    );

    staffApp.get<{ Params: EventParams; Querystring: ListRegistrationsQuery }>(
      "/events/:eventId/registrations",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);
        return registrationService.listRegistrations(eventId, request.query);
      },
    );

    staffApp.get<{ Params: EventParams; Querystring: ListWaitlistQuery }>(
      "/events/:eventId/waitlist",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);
        return registrationService.listWaitlist(eventId, request.query);
      },
    );
  });
};
