import {
  VALIDATION_ERROR_CODES,
  type RegistrationState,
} from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { EventWithConfig } from "../event/types.js";
import type { RegistrationRow } from "../registration/types.js";
import type { ActorContext, CheckinRecordRow } from "./types.js";

const SELF_CHECKIN_EVENT_STATES = ["InProgress"] as const;

export function assertAuditMetadata(context: ActorContext): void {
  if (!context.actorId?.trim() || !context.actorRole?.trim()) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.AUDIT_METADATA_MISSING,
      message: "Check-in requires actor identity for audit.",
      statusCode: 400,
    });
  }
}

export function assertCheckinWindowOpen(
  event: EventWithConfig,
  now: number = Date.now(),
): void {
  if (event.state === "Cancelled") {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED,
      message: "Check-in is not available for cancelled events.",
      statusCode: 422,
      details: { eventState: event.state },
    });
  }

  const openAt = new Date(event.ruleConfig.checkinOpenAt).getTime();
  const closeAt = new Date(event.ruleConfig.checkinCloseAt).getTime();

  if (Number.isNaN(openAt) || Number.isNaN(closeAt)) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED,
      message: "Check-in window is not configured.",
      statusCode: 422,
    });
  }

  if (now < openAt || now >= closeAt) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED,
      message: "Check-in is not available at this time.",
      statusCode: 422,
      details: {
        checkinOpenAt: event.ruleConfig.checkinOpenAt,
        checkinCloseAt: event.ruleConfig.checkinCloseAt,
      },
    });
  }
}

export function assertSelfCheckinAllowed(event: EventWithConfig): void {
  if (!event.ruleConfig.selfCheckinEnabled) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.SELF_CHECKIN_DISABLED,
      message: "Self check-in is not enabled for this event.",
      statusCode: 422,
      details: { selfCheckinEnabled: false },
    });
  }

  if (
    !SELF_CHECKIN_EVENT_STATES.includes(
      event.state as (typeof SELF_CHECKIN_EVENT_STATES)[number],
    )
  ) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED,
      message: "Self check-in is only available while the event is in progress.",
      statusCode: 422,
      details: { eventState: event.state },
    });
  }
}

export function assertNoExistingCheckin(
  existing: CheckinRecordRow | null,
): void {
  if (existing) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CHECKIN_ALREADY_RECORDED,
      message: "A valid check-in already exists for this registration.",
      statusCode: 409,
      details: {
        checkinId: existing.id,
        checkinAt: existing.checkinAt,
      },
    });
  }
}

export function assertRegistrationCheckinable(
  registration: RegistrationRow,
): void {
  if (registration.state === "CheckedIn") {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CHECKIN_ALREADY_RECORDED,
      message: "This registration is already checked in.",
      statusCode: 409,
      details: {
        registrationId: registration.id,
        state: registration.state,
      },
    });
  }

  if (registration.state !== "Registered") {
    throw new ApiError({
      code: "INVALID_STATE_TRANSITION",
      message: "Only registered participants can check in.",
      statusCode: 409,
      details: {
        registrationId: registration.id,
        state: registration.state,
      },
    });
  }
}

export function toCheckinResponse(
  record: CheckinRecordRow,
  registrationState: RegistrationState,
  participantId: string,
) {
  return {
    checkinId: record.id,
    registrationId: record.registrationId,
    eventId: record.eventId,
    participantId,
    checkinAt: record.checkinAt,
    method: record.method,
    operatorId: record.operatorId,
    registrationState,
  };
}
