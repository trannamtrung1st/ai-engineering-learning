import {
  VALIDATION_ERROR_CODES,
  type RegistrationState,
} from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { EventWithConfig } from "../event/types.js";
import type { RegistrationRow } from "./types.js";

const ACTIVE_REGISTRATION_STATES: RegistrationState[] = [
  "Requested",
  "Registered",
  "Waitlisted",
  "CheckedIn",
];

const SEAT_HOLDING_STATES: RegistrationState[] = ["Registered", "CheckedIn"];

export function isActiveRegistrationState(state: RegistrationState): boolean {
  return ACTIVE_REGISTRATION_STATES.includes(state);
}

export function assertRegistrationWindowOpen(event: EventWithConfig): void {
  if (event.state === "Cancelled") {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.REGISTRATION_WINDOW_CLOSED,
      message: "Registration is not available for cancelled events.",
      statusCode: 422,
      details: { eventState: event.state },
    });
  }

  if (event.state !== "RegistrationOpen") {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.REGISTRATION_WINDOW_CLOSED,
      message: "Registration is not open for this event.",
      statusCode: 422,
      details: { eventState: event.state },
    });
  }

  if (event.ruleConfig.registrationPaused) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.REGISTRATION_WINDOW_CLOSED,
      message: "Registration is temporarily paused for this event.",
      statusCode: 422,
      details: { registrationPaused: true },
    });
  }

  const now = Date.now();
  const openAt = new Date(event.ruleConfig.registrationOpenAt).getTime();
  const closeAt = new Date(event.ruleConfig.registrationCloseAt).getTime();

  if (Number.isNaN(openAt) || Number.isNaN(closeAt)) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.REGISTRATION_WINDOW_CLOSED,
      message: "Registration window is not configured.",
      statusCode: 422,
    });
  }

  if (now < openAt || now > closeAt) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.REGISTRATION_WINDOW_CLOSED,
      message: "Registration window is closed.",
      statusCode: 422,
      details: {
        registrationOpenAt: event.ruleConfig.registrationOpenAt,
        registrationCloseAt: event.ruleConfig.registrationCloseAt,
      },
    });
  }
}

export function assertNoDuplicateActive(
  existing: RegistrationRow | null,
): void {
  if (existing && isActiveRegistrationState(existing.state)) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.REGISTRATION_DUPLICATE_ACTIVE,
      message: "You already have an active registration for this event.",
      statusCode: 409,
      details: {
        registrationId: existing.id,
        state: existing.state,
      },
    });
  }
}

export function assertParticipantCancellationAllowed(
  event: EventWithConfig,
  registration: RegistrationRow,
): void {
  if (registration.state !== "Registered" && registration.state !== "Waitlisted") {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CANCELLATION_NOT_ALLOWED,
      message: "Only registered or waitlisted participants may cancel.",
      statusCode: 422,
      details: { state: registration.state },
    });
  }

  const now = Date.now();
  const closeAt = new Date(event.ruleConfig.registrationCloseAt).getTime();
  const pastDeadline = now > closeAt;
  const registrationPhaseOpen =
    event.state === "RegistrationOpen" || event.state === "Published";

  if (pastDeadline) {
    if (!registrationPhaseOpen) {
      throw new ApiError({
        code: VALIDATION_ERROR_CODES.CANCELLATION_NOT_ALLOWED,
        message: "Cancellation is not allowed after the registration period has ended.",
        statusCode: 422,
        details: {
          eventState: event.state,
          registrationCloseAt: event.ruleConfig.registrationCloseAt,
        },
      });
    }

    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CANCELLATION_DEADLINE_PASSED,
      message: "Cancellation deadline has passed.",
      statusCode: 422,
      details: { registrationCloseAt: event.ruleConfig.registrationCloseAt },
    });
  }

  if (!registrationPhaseOpen) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CANCELLATION_NOT_ALLOWED,
      message: "Cancellation is not allowed after the registration period has ended.",
      statusCode: 422,
      details: { eventState: event.state },
    });
  }
}

export function assertOrganizerCancellationAllowed(
  registration: RegistrationRow,
): void {
  if (registration.state !== "Registered" && registration.state !== "Waitlisted") {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.CANCELLATION_NOT_ALLOWED,
      message: "Only active registrations or waitlist entries may be cancelled.",
      statusCode: 422,
      details: { state: registration.state },
    });
  }
}

export function toRegistrationResponse(
  registration: RegistrationRow,
  waitlistPosition: number | null = null,
) {
  return {
    registrationId: registration.id,
    eventId: registration.eventId,
    participantId: registration.participantId,
    state: registration.state,
    reasonCode: registration.statusReasonCode,
    reasonText: registration.statusReasonText,
    waitlistPosition,
    requestedAt: registration.requestedAt,
    updatedAt: registration.updatedAt,
    version: registration.version,
  };
}

export { SEAT_HOLDING_STATES };
