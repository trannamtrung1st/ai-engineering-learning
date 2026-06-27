import type { FastifyPluginAsync } from "fastify";
import { assertEventScope } from "../../auth/scope.js";
import { getActor, requireRole } from "../../auth/middleware.js";
import { ApiError } from "../../errors/api-error.js";
import { ensureEligibilitySchema } from "./repository.js";
import { eligibilityService } from "./service.js";
import type { RevokeEligibilityInput, ListEligibilityQuery, ExportEventQuery } from "./types.js";

interface EventParams {
  eventId: string;
}

interface RevokeParams extends EventParams {
  registrationId: string;
}

export const eligibilityRoutes: FastifyPluginAsync = async (app) => {
  await ensureEligibilitySchema();

  app.get<{ Params: EventParams }>(
    "/events/:eventId/eligibility/me",
    async (request) => {
      const actor = getActor(request);
      if (actor.role !== "Participant") {
        throw new ApiError({
          code: "FORBIDDEN",
          message: "Only participants can view their own eligibility.",
          statusCode: 403,
        });
      }

      const { eventId } = request.params;
      return eligibilityService.getMyEligibility(eventId, actor.sub, {
        actorId: actor.sub,
        actorRole: actor.role,
      });
    },
  );

  app.register(async (staffApp) => {
    staffApp.addHook(
      "onRequest",
      requireRole("OrganizerAdmin", "OrganizerStaff"),
    );

    staffApp.get<{ Params: EventParams; Querystring: ListEligibilityQuery }>(
      "/events/:eventId/eligibility",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);
        return eligibilityService.listEligibility(
          eventId,
          request.query,
          {
            actorId: actor.sub,
            actorRole: actor.role,
          },
        );
      },
    );

    staffApp.get<{ Params: EventParams; Querystring: ExportEventQuery }>(
      "/events/:eventId/export",
      async (request, reply) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);

        const exportType = request.query.type?.trim() || "eligibility";
        if (exportType !== "eligibility") {
          throw new ApiError({
            code: "INVALID_INPUT",
            message: "Unsupported export type.",
            statusCode: 400,
            details: { type: exportType },
          });
        }

        const result = await eligibilityService.exportEligibilityCsv(
          eventId,
          request.query,
          {
            actorId: actor.sub,
            actorRole: actor.role,
          },
        );

        return reply
          .header("Content-Type", "text/csv; charset=utf-8")
          .header(
            "Content-Disposition",
            `attachment; filename="${result.filename}"`,
          )
          .header("X-Export-Row-Count", String(result.rowCount))
          .send(result.csv);
      },
    );
  });

  app.post<{ Params: RevokeParams; Body: RevokeEligibilityInput }>(
    "/events/:eventId/eligibility/:registrationId/revoke",
    async (request) => {
      const actor = getActor(request);
      if (actor.role !== "OrganizerAdmin") {
        throw new ApiError({
          code: "FORBIDDEN",
          message: "Only organizer admins may revoke eligibility.",
          statusCode: 403,
        });
      }

      const { eventId, registrationId } = request.params;
      assertEventScope(actor, eventId);

      const body = request.body;
      if (!body?.reasonCode?.trim() || !body?.reasonText?.trim()) {
        throw new ApiError({
          code: "INVALID_INPUT",
          message: "reasonCode and reasonText are required.",
          statusCode: 400,
        });
      }

      return eligibilityService.revoke(
        eventId,
        registrationId,
        body,
        { actorId: actor.sub, actorRole: actor.role },
      );
    },
  );
};
