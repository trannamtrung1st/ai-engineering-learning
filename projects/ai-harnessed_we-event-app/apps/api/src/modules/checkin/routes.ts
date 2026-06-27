import type { FastifyPluginAsync } from "fastify";
import { assertEventScope } from "../../auth/scope.js";
import { getActor, requireRole } from "../../auth/middleware.js";
import { resolveActorId } from "../../auth/resolve-actor-id.js";
import { ApiError } from "../../errors/api-error.js";
import {
  ensureIdempotencySchema,
  executeIdempotent,
} from "../../idempotency/index.js";
import { ensureCheckinSchema } from "./repository.js";
import { checkinService } from "./service.js";
import type { ListAttendanceQuery, StaffCheckinInput } from "./types.js";

interface EventParams {
  eventId: string;
}

export const checkinRoutes: FastifyPluginAsync = async (app) => {
  await ensureCheckinSchema();
  await ensureIdempotencySchema();

  app.post<{ Params: EventParams; Body: StaffCheckinInput }>(
    "/events/:eventId/self-checkin",
    async (request) => {
      const actor = getActor(request);
      if (actor.role !== "Participant") {
        throw new ApiError({
          code: "FORBIDDEN",
          message: "Only participants can use self check-in.",
          statusCode: 403,
        });
      }

      const { eventId } = request.params;
      const resolvedSub = resolveActorId(actor.sub);
      const context = { actorId: resolvedSub, actorRole: actor.role };
      const fingerprint = JSON.stringify({ eventId, participantId: resolvedSub });

      return executeIdempotent(
        request.headers,
        resolvedSub,
        `checkin.self:${eventId}`,
        fingerprint,
        () => checkinService.selfCheckin(eventId, resolvedSub, context),
      );
    },
  );

  app.register(async (staffApp) => {
    staffApp.addHook(
      "onRequest",
      requireRole("OrganizerAdmin", "OrganizerStaff"),
    );

    staffApp.post<{ Params: EventParams; Body: StaffCheckinInput }>(
      "/events/:eventId/checkins",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);

        const body = request.body;
        if (!body?.registrationId?.trim()) {
          throw new ApiError({
            code: "INVALID_INPUT",
            message: "registrationId is required.",
            statusCode: 400,
          });
        }

        const resolvedSub = resolveActorId(actor.sub);
        const context = { actorId: resolvedSub, actorRole: actor.role };
        const fingerprint = JSON.stringify({
          eventId,
          registrationId: body.registrationId,
        });

        return executeIdempotent(
          request.headers,
          resolvedSub,
          `checkin.staff:${eventId}:${body.registrationId}`,
          fingerprint,
          () => checkinService.staffCheckin(eventId, body, context),
        );
      },
    );

    staffApp.get<{ Params: EventParams; Querystring: ListAttendanceQuery }>(
      "/events/:eventId/attendance",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);
        return checkinService.listAttendance(eventId, request.query);
      },
    );
  });
};
