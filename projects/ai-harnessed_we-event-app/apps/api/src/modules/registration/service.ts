import { ApiError } from "../../errors/api-error.js";
import { findEventById } from "../event/repository.js";
import {
  cancelRegistration,
  createRegistration,
  findActiveRegistration,
  findRegistrationById,
  listRegistrationsForEvent,
  listWaitlistForEvent,
  loadRegistrationWithWaitlist,
} from "./repository.js";
import type { ActorContext, CancelInput } from "./types.js";
import {
  assertNoDuplicateActive,
  assertOrganizerCancellationAllowed,
  assertParticipantCancellationAllowed,
  assertRegistrationWindowOpen,
  toRegistrationResponse,
} from "./validation.js";

export class RegistrationService {
  async register(
    eventId: string,
    participantId: string,
    context: ActorContext,
  ) {
    const event = await this.requireEvent(eventId);
    assertRegistrationWindowOpen(event);

    const existing = await findActiveRegistration(eventId, participantId);
    assertNoDuplicateActive(existing);

    const registration = await createRegistration(
      eventId,
      participantId,
      context,
    );

    return toRegistrationResponse(registration, registration.waitlistPosition);
  }

  async getStatus(eventId: string, participantId: string) {
    const registration = await findActiveRegistration(eventId, participantId);
    if (!registration) {
      return { registration: null };
    }
    const withWaitlist = await loadRegistrationWithWaitlist(registration);
    return {
      registration: toRegistrationResponse(
        withWaitlist,
        withWaitlist.waitlistPosition,
      ),
    };
  }

  async cancel(
    eventId: string,
    registrationId: string,
    context: ActorContext,
    input: CancelInput = {},
    options: { asOrganizer?: boolean } = {},
  ) {
    const registration = await this.requireRegistration(registrationId, eventId);
    const event = await this.requireEvent(eventId);

    if (options.asOrganizer) {
      assertOrganizerCancellationAllowed(registration);
    } else {
      if (registration.participantId !== context.actorId) {
        throw new ApiError({
          code: "FORBIDDEN",
          message: "You can only cancel your own registration.",
          statusCode: 403,
          details: { registrationId },
        });
      }
      assertParticipantCancellationAllowed(event, registration);
    }

    const cancelledState = options.asOrganizer
      ? "CancelledByOrganizer"
      : "CancelledByUser";

    const result = await cancelRegistration(registration, cancelledState, {
      ...context,
      reasonCode: input.reasonCode,
      reasonText: input.reasonText,
    });

    const cancelled = await loadRegistrationWithWaitlist(result.cancelled);

    return {
      cancelled: toRegistrationResponse(
        cancelled,
        cancelled.waitlistPosition,
      ),
      promoted: result.promoted
        ? toRegistrationResponse(result.promoted, null)
        : null,
    };
  }

  async listRegistrations(eventId: string) {
    await this.requireEvent(eventId);
    const registrations = await listRegistrationsForEvent(eventId);
    return {
      registrations: registrations.map((row) =>
        toRegistrationResponse(row, row.waitlistPosition),
      ),
    };
  }

  async listWaitlist(eventId: string) {
    await this.requireEvent(eventId);
    const entries = await listWaitlistForEvent(eventId);
    return { waitlist: entries };
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

  private async requireRegistration(registrationId: string, eventId: string) {
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
}

export const registrationService = new RegistrationService();
