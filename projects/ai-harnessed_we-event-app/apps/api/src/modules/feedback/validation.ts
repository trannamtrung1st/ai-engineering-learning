import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { EventWithConfig } from "../event/types.js";
import type { RegistrationRow } from "../registration/types.js";
import type { FeedbackRow } from "./types.js";

const FEEDBACK_ALLOWED_EVENT_STATES = ["Completed"] as const;
const FEEDBACK_ALLOWED_REGISTRATION_STATES = ["Attended"] as const;

const MAX_ANSWER_KEYS = 50;
const MAX_ANSWER_TEXT_LENGTH = 4000;

export function assertFeedbackWindowOpen(
  event: EventWithConfig,
  now: number = Date.now(),
): void {
  if (event.state === "Cancelled") {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.FEEDBACK_NOT_ALLOWED,
      message: "Feedback is not available for cancelled events.",
      statusCode: 422,
      details: { eventState: event.state },
    });
  }

  if (
    !FEEDBACK_ALLOWED_EVENT_STATES.includes(
      event.state as (typeof FEEDBACK_ALLOWED_EVENT_STATES)[number],
    )
  ) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.FEEDBACK_NOT_ALLOWED,
      message: "Feedback is only available after the event is completed.",
      statusCode: 422,
      details: { eventState: event.state },
    });
  }

  const openAt = new Date(event.ruleConfig.feedbackOpenAt).getTime();
  const closeAt = new Date(event.ruleConfig.feedbackCloseAt).getTime();

  if (Number.isNaN(openAt) || Number.isNaN(closeAt)) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.FEEDBACK_NOT_ALLOWED,
      message: "Feedback window is not configured.",
      statusCode: 422,
    });
  }

  if (now < openAt || now > closeAt) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.FEEDBACK_NOT_ALLOWED,
      message: "Feedback is not available at this time.",
      statusCode: 422,
      details: {
        feedbackOpenAt: event.ruleConfig.feedbackOpenAt,
        feedbackCloseAt: event.ruleConfig.feedbackCloseAt,
      },
    });
  }
}

export function assertRegistrationFeedbackEligible(
  registration: RegistrationRow,
): void {
  if (
    !FEEDBACK_ALLOWED_REGISTRATION_STATES.includes(
      registration.state as (typeof FEEDBACK_ALLOWED_REGISTRATION_STATES)[number],
    )
  ) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.FEEDBACK_NOT_ALLOWED,
      message: "Only attended participants may submit feedback.",
      statusCode: 422,
      details: {
        registrationId: registration.id,
        state: registration.state,
      },
    });
  }
}

export function assertAnswersValid(answers: Record<string, unknown>): void {
  if (!answers || typeof answers !== "object" || Array.isArray(answers)) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "answers must be a JSON object.",
      statusCode: 400,
    });
  }

  const keys = Object.keys(answers);
  if (keys.length === 0) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "answers must include at least one response.",
      statusCode: 400,
    });
  }

  if (keys.length > MAX_ANSWER_KEYS) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: `answers may include at most ${MAX_ANSWER_KEYS} fields.`,
      statusCode: 400,
    });
  }

  for (const key of keys) {
    const value = answers[key];
    if (typeof value === "string" && value.length > MAX_ANSWER_TEXT_LENGTH) {
      throw new ApiError({
        code: "INVALID_INPUT",
        message: `Answer for "${key}" exceeds the maximum length.`,
        statusCode: 400,
      });
    }
  }
}

export function assertNoDuplicateOutsideWindow(
  existing: FeedbackRow | null,
  allowUpdate: boolean,
): void {
  if (existing && !allowUpdate) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.FEEDBACK_DUPLICATE,
      message: "Official feedback has already been submitted for this event.",
      statusCode: 409,
      details: {
        feedbackId: existing.id,
        submittedAt: existing.submittedAt,
      },
    });
  }
}

export function toFeedbackResponse(row: FeedbackRow) {
  return {
    feedbackId: row.id,
    eventId: row.eventId,
    registrationId: row.registrationId,
    participantId: row.participantId,
    submittedAt: row.submittedAt,
    answers: row.payload,
  };
}
