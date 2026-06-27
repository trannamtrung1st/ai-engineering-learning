import { actorIdsMatch, resolveActorId } from "../../auth/resolve-actor-id.js";
import { ApiError } from "../../errors/api-error.js";
import { findEventById } from "../event/repository.js";
import { findRegistrationById, findRegistrationByParticipant } from "../registration/repository.js";
import {
  findFeedbackByRegistrationId,
  submitOrUpdateFeedback,
} from "./repository.js";
import type { ActorContext, SubmitFeedbackInput } from "./types.js";
import {
  assertAnswersValid,
  assertFeedbackWindowOpen,
  assertRegistrationFeedbackEligible,
  toFeedbackResponse,
} from "./validation.js";

export class FeedbackService {
  async submit(
    eventId: string,
    participantId: string,
    input: SubmitFeedbackInput,
    context: ActorContext,
  ) {
    assertAnswersValid(input.answers);

    const resolvedParticipantId = resolveActorId(participantId);
    const resolvedContext: ActorContext = {
      ...context,
      actorId: resolveActorId(context.actorId),
    };

    const event = await this.requireEvent(eventId);
    assertFeedbackWindowOpen(event);

    const registration = await this.resolveRegistration(
      eventId,
      resolvedParticipantId,
      input.registrationId,
    );
    assertRegistrationFeedbackEligible(registration);

    if (!actorIdsMatch(registration.participantId, resolvedParticipantId)) {
      throw new ApiError({
        code: "FORBIDDEN",
        message: "You can only submit feedback for your own registration.",
        statusCode: 403,
      });
    }

    const existing = await findFeedbackByRegistrationId(registration.id);
    const row = await submitOrUpdateFeedback(
      registration,
      input.answers,
      resolvedContext,
      existing,
    );

    return toFeedbackResponse(row);
  }

  private async resolveRegistration(
    eventId: string,
    participantId: string,
    registrationId?: string,
  ) {
    if (registrationId?.trim()) {
      const registration = await findRegistrationById(registrationId);
      if (!registration || registration.eventId !== eventId) {
        throw new ApiError({
          code: "NOT_FOUND",
          message: "Registration not found.",
          statusCode: 404,
          details: { registrationId, eventId },
        });
      }
      return registration;
    }

    const registration = await findRegistrationByParticipant(
      eventId,
      participantId,
      ["Attended"],
    );
    if (!registration) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "No attended registration found for this event.",
        statusCode: 404,
        details: { eventId, participantId },
      });
    }
    return registration;
  }

  private async requireEvent(eventId: string) {
    const event = await findEventById(eventId);
    if (!event) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Event not found.",
        statusCode: 404,
        details: { eventId },
      });
    }
    return event;
  }
}

export const feedbackService = new FeedbackService();
