import { ApiError } from "../../errors/api-error.js";
import { findEventById } from "../event/repository.js";
import {
  findActiveRegistration,
  findRegistrationById,
} from "../registration/repository.js";
import {
  findCheckinByRegistrationId,
  listAttendanceForEvent,
  recordCheckin,
} from "./repository.js";
import type { ActorContext, StaffCheckinInput } from "./types.js";
import {
  assertAuditMetadata,
  assertCheckinWindowOpen,
  assertNoExistingCheckin,
  assertRegistrationCheckinable,
  assertSelfCheckinAllowed,
  toCheckinResponse,
} from "./validation.js";

export class CheckinService {
  async staffCheckin(
    eventId: string,
    input: StaffCheckinInput,
    context: ActorContext,
  ) {
    assertAuditMetadata(context);

    const event = await this.requireEvent(eventId);
    assertCheckinWindowOpen(event);

    const registration = await this.requireRegistration(
      input.registrationId,
      eventId,
    );
    assertRegistrationCheckinable(registration);

    const existing = await findCheckinByRegistrationId(registration.id);
    assertNoExistingCheckin(existing);

    const result = await recordCheckin(
      registration,
      "Staff",
      context,
      context.actorId,
    );

    return toCheckinResponse(
      result.record,
      result.registration.state,
      result.registration.participantId,
    );
  }

  async selfCheckin(eventId: string, participantId: string, context: ActorContext) {
    assertAuditMetadata(context);

    const event = await this.requireEvent(eventId);
    assertSelfCheckinAllowed(event);
    assertCheckinWindowOpen(event);

    const registration = await findActiveRegistration(eventId, participantId);
    if (!registration) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "No active registration found for this event.",
        statusCode: 404,
        details: { eventId, participantId },
      });
    }

    if (registration.participantId !== participantId) {
      throw new ApiError({
        code: "FORBIDDEN",
        message: "You can only check in with your own registration.",
        statusCode: 403,
      });
    }

    assertRegistrationCheckinable(registration);

    const existing = await findCheckinByRegistrationId(registration.id);
    assertNoExistingCheckin(existing);

    const result = await recordCheckin(registration, "Self", context, null);

    return toCheckinResponse(
      result.record,
      result.registration.state,
      result.registration.participantId,
    );
  }

  async listAttendance(eventId: string) {
    await this.requireEvent(eventId);
    const attendance = await listAttendanceForEvent(eventId);
    return { attendance };
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

export const checkinService = new CheckinService();
