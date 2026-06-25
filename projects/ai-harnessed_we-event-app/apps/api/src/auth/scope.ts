import { ApiError } from "../errors/api-error.js";
import type { JwtPayload } from "./types.js";

/**
 * FR-26: Participants may only access their own registration-related records.
 * Other roles bypass this check and use event-scope or role guards instead.
 */
export function assertParticipantOwnership(
  actor: JwtPayload,
  participantId: string,
): void {
  if (actor.role !== "Participant") {
    return;
  }

  if (actor.sub !== participantId) {
    throw new ApiError({
      code: "FORBIDDEN",
      message: "You can only access your own registration data.",
      statusCode: 403,
      details: { participantId },
    });
  }
}

/**
 * OrganizerStaff may only operate on assigned events; OrganizerAdmin is unrestricted.
 */
export function assertEventScope(actor: JwtPayload, eventId: string): void {
  if (actor.role === "OrganizerAdmin") {
    return;
  }

  if (actor.role === "OrganizerStaff") {
    const assigned = actor.assignedEventIds ?? [];
    if (!assigned.includes(eventId)) {
      throw new ApiError({
        code: "FORBIDDEN",
        message: "You do not have access to this event.",
        statusCode: 403,
        details: { eventId },
      });
    }
    return;
  }

  throw new ApiError({
    code: "FORBIDDEN",
    message: "You do not have permission to access this event.",
    statusCode: 403,
    details: { eventId },
  });
}
