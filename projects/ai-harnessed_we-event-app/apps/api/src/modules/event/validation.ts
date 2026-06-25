import {
  EVENT_STATE_TRANSITIONS,
  VALIDATION_ERROR_CODES,
  type EventState,
  type EventTransitionTrigger,
} from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type {
  CreateEventInput,
  EventWithConfig,
  RuleConfigInput,
  UpdateEventInput,
} from "./types.js";

const DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001";

const POST_REGISTRATION_OPEN_STATES: EventState[] = [
  "RegistrationOpen",
  "RegistrationClosed",
  "InProgress",
  "Completed",
  "Archived",
  "Cancelled",
];

function parseIsoDate(value: string, field: string): Date {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: `${field} must be a valid ISO-8601 timestamp.`,
      statusCode: 400,
      details: { field, value },
    });
  }
  return date;
}

function assertWindowOpenBeforeClose(
  openAt: string,
  closeAt: string,
  label: string,
): void {
  const open = parseIsoDate(openAt, `${label}OpenAt`);
  const close = parseIsoDate(closeAt, `${label}CloseAt`);
  if (open >= close) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: `${label} window must have open time before close time.`,
      statusCode: 422,
      details: { openAt, closeAt },
    });
  }
}

export function validateRuleConfig(config: RuleConfigInput): void {
  if (!Number.isInteger(config.capacity) || config.capacity < 0) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "capacity must be a non-negative integer.",
      statusCode: 400,
    });
  }

  assertWindowOpenBeforeClose(
    config.registrationOpenAt,
    config.registrationCloseAt,
    "registration",
  );
  assertWindowOpenBeforeClose(
    config.checkinOpenAt,
    config.checkinCloseAt,
    "checkin",
  );
  assertWindowOpenBeforeClose(
    config.feedbackOpenAt,
    config.feedbackCloseAt,
    "feedback",
  );
}

export function validateCreateInput(input: CreateEventInput): CreateEventInput {
  if (!input.name?.trim()) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "name is required.",
      statusCode: 400,
    });
  }

  const startAt = parseIsoDate(input.startAt, "startAt");
  const endAt = parseIsoDate(input.endAt, "endAt");
  if (startAt >= endAt) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "startAt must be before endAt.",
      statusCode: 422,
    });
  }

  validateRuleConfig(input.ruleConfig);

  return {
    ...input,
    organizationId: input.organizationId ?? DEFAULT_ORGANIZATION_ID,
    name: input.name.trim(),
    description: input.description?.trim() ?? "",
    location: input.location?.trim() ?? "",
  };
}

export function validateUpdateInput(
  existing: EventWithConfig,
  input: UpdateEventInput,
): UpdateEventInput {
  const startAt = input.startAt ?? existing.startAt;
  const endAt = input.endAt ?? existing.endAt;
  const start = parseIsoDate(startAt, "startAt");
  const end = parseIsoDate(endAt, "endAt");
  if (start >= end) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "startAt must be before endAt.",
      statusCode: 422,
    });
  }

  if (input.ruleConfig) {
    const merged: RuleConfigInput = {
      capacity: input.ruleConfig.capacity ?? existing.ruleConfig.capacity,
      waitlistEnabled:
        input.ruleConfig.waitlistEnabled ?? existing.ruleConfig.waitlistEnabled,
      registrationOpenAt:
        input.ruleConfig.registrationOpenAt ??
        existing.ruleConfig.registrationOpenAt,
      registrationCloseAt:
        input.ruleConfig.registrationCloseAt ??
        existing.ruleConfig.registrationCloseAt,
      checkinOpenAt:
        input.ruleConfig.checkinOpenAt ?? existing.ruleConfig.checkinOpenAt,
      checkinCloseAt:
        input.ruleConfig.checkinCloseAt ?? existing.ruleConfig.checkinCloseAt,
      feedbackRequired:
        input.ruleConfig.feedbackRequired ??
        existing.ruleConfig.feedbackRequired,
      feedbackOpenAt:
        input.ruleConfig.feedbackOpenAt ?? existing.ruleConfig.feedbackOpenAt,
      feedbackCloseAt:
        input.ruleConfig.feedbackCloseAt ?? existing.ruleConfig.feedbackCloseAt,
    };
    validateRuleConfig(merged);

    if (
      POST_REGISTRATION_OPEN_STATES.includes(existing.state) &&
      hasCriticalRuleChange(existing.ruleConfig, input.ruleConfig)
    ) {
      if (!input.reasonCode?.trim() || !input.reasonText?.trim()) {
        throw new ApiError({
          code: VALIDATION_ERROR_CODES.AUDIT_REQUIRED_FOR_CRITICAL_CHANGE,
          message:
            "Critical rule changes after registration opens require reasonCode and reasonText.",
          statusCode: 422,
        });
      }
    } else if (
      POST_REGISTRATION_OPEN_STATES.includes(existing.state) &&
      input.ruleConfig &&
      hasAnyRuleFieldChange(existing.ruleConfig, input.ruleConfig)
    ) {
      throw new ApiError({
        code: VALIDATION_ERROR_CODES.EVENT_RULE_CHANGE_FORBIDDEN,
        message:
          "Only critical rule changes are allowed after registration opens.",
        statusCode: 403,
      });
    }
  }

  if (
    hasMetadataChange(input) &&
    existing.state !== "Draft" &&
    existing.state !== "Published"
  ) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.EVENT_RULE_CHANGE_FORBIDDEN,
      message: "Event metadata can only be edited in Draft or Published state.",
      statusCode: 403,
    });
  }

  return input;
}

function hasMetadataChange(input: UpdateEventInput): boolean {
  return (
    input.name !== undefined ||
    input.description !== undefined ||
    input.location !== undefined ||
    input.startAt !== undefined ||
    input.endAt !== undefined
  );
}

function hasCriticalRuleChange(
  existing: EventWithConfig["ruleConfig"],
  patch: NonNullable<UpdateEventInput["ruleConfig"]>,
): boolean {
  const criticalKeys: (keyof typeof patch)[] = [
    "capacity",
    "waitlistEnabled",
    "registrationOpenAt",
    "registrationCloseAt",
    "checkinOpenAt",
    "checkinCloseAt",
    "feedbackRequired",
    "feedbackOpenAt",
    "feedbackCloseAt",
  ];

  return criticalKeys.some((key) => {
    const value = patch[key];
    if (value === undefined) {
      return false;
    }
    return value !== existing[key as keyof typeof existing];
  });
}

function hasAnyRuleFieldChange(
  existing: EventWithConfig["ruleConfig"],
  patch: NonNullable<UpdateEventInput["ruleConfig"]>,
): boolean {
  const keys: (keyof typeof patch)[] = [
    "capacity",
    "waitlistEnabled",
    "registrationOpenAt",
    "registrationCloseAt",
    "checkinOpenAt",
    "checkinCloseAt",
    "feedbackRequired",
    "feedbackOpenAt",
    "feedbackCloseAt",
    "registrationPaused",
  ];

  return keys.some((key) => {
    const value = patch[key];
    if (value === undefined) {
      return false;
    }
    return value !== existing[key as keyof typeof existing];
  });
}

export function assertPublishReady(event: EventWithConfig): void {
  const missing: string[] = [];
  if (!event.name.trim()) {
    missing.push("name");
  }
  if (!event.location.trim()) {
    missing.push("location");
  }
  if (!event.startAt || !event.endAt) {
    missing.push("schedule");
  }

  try {
    validateRuleConfig({
      capacity: event.ruleConfig.capacity,
      waitlistEnabled: event.ruleConfig.waitlistEnabled,
      registrationOpenAt: event.ruleConfig.registrationOpenAt,
      registrationCloseAt: event.ruleConfig.registrationCloseAt,
      checkinOpenAt: event.ruleConfig.checkinOpenAt,
      checkinCloseAt: event.ruleConfig.checkinCloseAt,
      feedbackRequired: event.ruleConfig.feedbackRequired,
      feedbackOpenAt: event.ruleConfig.feedbackOpenAt,
      feedbackCloseAt: event.ruleConfig.feedbackCloseAt,
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw new ApiError({
        code: "INVALID_INPUT",
        message: "Event rule configuration is incomplete or invalid for publish.",
        statusCode: 422,
        details: { issues: error.details },
      });
    }
    throw error;
  }

  if (missing.length > 0) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "Required event fields are incomplete for publish.",
      statusCode: 422,
      details: { missing },
    });
  }
}

export function resolveTransition(
  from: EventState,
  trigger: EventTransitionTrigger,
): EventState {
  const match = EVENT_STATE_TRANSITIONS.find(
    (transition) => transition.from === from && transition.trigger === trigger,
  );
  if (!match) {
    throw new ApiError({
      code: "INVALID_STATE_TRANSITION",
      message: `Cannot apply ${trigger} while event is in ${from} state.`,
      statusCode: 409,
      details: { from, trigger },
    });
  }
  return match.to;
}

export function toEventResponse(event: EventWithConfig) {
  return {
    eventId: event.id,
    organizationId: event.organizationId,
    name: event.name,
    description: event.description,
    location: event.location,
    state: event.state,
    startAt: event.startAt,
    endAt: event.endAt,
    version: event.version,
    updatedAt: event.updatedAt,
    ruleConfig: {
      capacity: event.ruleConfig.capacity,
      waitlistEnabled: event.ruleConfig.waitlistEnabled,
      registrationOpenAt: event.ruleConfig.registrationOpenAt,
      registrationCloseAt: event.ruleConfig.registrationCloseAt,
      checkinOpenAt: event.ruleConfig.checkinOpenAt,
      checkinCloseAt: event.ruleConfig.checkinCloseAt,
      feedbackRequired: event.ruleConfig.feedbackRequired,
      feedbackOpenAt: event.ruleConfig.feedbackOpenAt,
      feedbackCloseAt: event.ruleConfig.feedbackCloseAt,
      registrationPaused: event.ruleConfig.registrationPaused,
      version: event.ruleConfig.version,
    },
  };
}

export { DEFAULT_ORGANIZATION_ID };
