import type { FastifyPluginAsync } from "fastify";
import { getActor } from "../../auth/middleware.js";
import { ApiError } from "../../errors/api-error.js";
import { ensureFeedbackSchema } from "./repository.js";
import { feedbackService } from "./service.js";
import type { SubmitFeedbackInput } from "./types.js";

interface EventParams {
  eventId: string;
}

export const feedbackRoutes: FastifyPluginAsync = async (app) => {
  await ensureFeedbackSchema();

  app.post<{ Params: EventParams; Body: SubmitFeedbackInput }>(
    "/events/:eventId/feedback",
    async (request) => {
      const actor = getActor(request);
      if (actor.role !== "Participant") {
        throw new ApiError({
          code: "FORBIDDEN",
          message: "Only participants can submit feedback.",
          statusCode: 403,
        });
      }

      const { eventId } = request.params;
      const body = request.body;
      if (!body?.answers) {
        throw new ApiError({
          code: "INVALID_INPUT",
          message: "answers is required.",
          statusCode: 400,
        });
      }

      return feedbackService.submit(
        eventId,
        actor.sub,
        body,
        { actorId: actor.sub, actorRole: actor.role },
      );
    },
  );
};
