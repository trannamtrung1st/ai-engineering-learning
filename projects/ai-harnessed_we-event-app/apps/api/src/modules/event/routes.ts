import type { FastifyPluginAsync, FastifyRequest } from "fastify";
import { getActor, requireRole } from "../../auth/middleware.js";
import { assertEventScope } from "../../auth/scope.js";
import { ensureEventSchema } from "./repository.js";
import { eventService } from "./service.js";
import type {
  CreateEventInput,
  ListEventsQuery,
  RuleConfigInput,
  UpdateEventInput,
} from "./types.js";

interface ReasonBody {
  reasonCode?: string;
  reasonText?: string;
}

interface CreateEventBody extends CreateEventInput {
  ruleConfig: RuleConfigInput;
}

interface EventParams {
  eventId: string;
}

export const eventRoutes: FastifyPluginAsync = async (app) => {
  await ensureEventSchema();

  app.get<{ Querystring: ListEventsQuery }>("/events", async (request) => {
    const actor = getActor(request);
    return eventService.list(actor.role, request.query);
  });

  app.get<{ Params: EventParams }>("/events/:eventId", async (request) => {
    const actor = getActor(request);
    const { eventId } = request.params;
    if (actor.role !== "Participant") {
      assertEventScope(actor, eventId);
    }
    return eventService.getById(eventId, actor.role);
  });

  app.register(async (adminApp) => {
    adminApp.addHook("onRequest", requireRole("OrganizerAdmin"));

    adminApp.post<{ Body: CreateEventBody }>("/events", async (request) => {
      const actor = getActor(request);
      return eventService.create(request.body, actor.sub, actor.role);
    });

    adminApp.patch<{ Params: EventParams; Body: UpdateEventInput }>(
      "/events/:eventId",
      async (request) => {
        const actor = getActor(request);
        const { eventId } = request.params;
        assertEventScope(actor, eventId);
        return eventService.update(eventId, request.body, {
          actorId: actor.sub,
          actorRole: actor.role,
          reasonCode: request.body.reasonCode,
          reasonText: request.body.reasonText,
        });
      },
    );

    const registerTransition = (
      path: string,
      handler: (
        eventId: string,
        context: {
          actorId: string;
          actorRole: string;
          reasonCode?: string;
          reasonText?: string;
        },
      ) => Promise<unknown>,
    ) => {
      adminApp.post<{ Params: EventParams; Body?: ReasonBody }>(
        path,
        async (request: FastifyRequest<{ Params: EventParams; Body?: ReasonBody }>) => {
          const actor = getActor(request);
          const { eventId } = request.params;
          assertEventScope(actor, eventId);
          return handler(eventId, {
            actorId: actor.sub,
            actorRole: actor.role,
            reasonCode: request.body?.reasonCode,
            reasonText: request.body?.reasonText,
          });
        },
      );
    };

    registerTransition("/events/:eventId/publish", (eventId, ctx) =>
      eventService.publish(eventId, ctx),
    );
    registerTransition("/events/:eventId/pause", (eventId, ctx) =>
      eventService.pause(eventId, ctx),
    );
    registerTransition("/events/:eventId/open-registration", (eventId, ctx) =>
      eventService.openRegistration(eventId, ctx),
    );
    registerTransition("/events/:eventId/close-registration", (eventId, ctx) =>
      eventService.closeRegistration(eventId, ctx),
    );
    registerTransition("/events/:eventId/start", (eventId, ctx) =>
      eventService.start(eventId, ctx),
    );
    registerTransition("/events/:eventId/complete", (eventId, ctx) =>
      eventService.complete(eventId, ctx),
    );
    registerTransition("/events/:eventId/cancel", (eventId, ctx) =>
      eventService.cancel(eventId, ctx),
    );
  });
};
