import type { EventTransitionTrigger } from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import {
  createEvent,
  findEventById,
  listEvents,
  organizationExists,
  transitionEventState,
  updateEvent,
} from "./repository.js";
import type {
  CreateEventInput,
  EventWithConfig,
  TransitionContext,
  UpdateEventInput,
} from "./types.js";
import {
  assertPublishReady,
  resolveTransition,
  toEventResponse,
  validateCreateInput,
  validateUpdateInput,
} from "./validation.js";

const PARTICIPANT_VISIBLE_STATES = [
  "Published",
  "RegistrationOpen",
  "RegistrationClosed",
  "InProgress",
  "Completed",
  "Archived",
] as const;

export class EventService {
  async create(
    input: CreateEventInput,
    actorId: string,
    actorRole: string,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const validated = validateCreateInput(input);
    const organizationId = validated.organizationId!;

    if (!(await organizationExists(organizationId))) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Organization not found.",
        statusCode: 404,
        details: { organizationId },
      });
    }

    const event = await createEvent(validated, actorId, actorRole, organizationId);
    return toEventResponse(event);
  }

  async getById(
    eventId: string,
    role: string,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const event = await this.requireEvent(eventId);

    if (
      role === "Participant" &&
      !PARTICIPANT_VISIBLE_STATES.includes(
        event.state as (typeof PARTICIPANT_VISIBLE_STATES)[number],
      )
    ) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Event not found.",
        statusCode: 404,
        details: { eventId },
      });
    }

    return toEventResponse(event);
  }

  async list(role: string): Promise<ReturnType<typeof toEventResponse>[]> {
    const states =
      role === "Participant" ? [...PARTICIPANT_VISIBLE_STATES] : undefined;
    const events = await listEvents({ states });
    return events.map(toEventResponse);
  }

  async update(
    eventId: string,
    input: UpdateEventInput,
    context: TransitionContext,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const existing = await this.requireEvent(eventId);
    const validated = validateUpdateInput(existing, input);

    const updated = await updateEvent(
      eventId,
      validated,
      context.actorId,
      context.actorRole,
    );
    if (!updated) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Event not found.",
        statusCode: 404,
        details: { eventId },
      });
    }
    return toEventResponse(updated);
  }

  async publish(
    eventId: string,
    context: TransitionContext,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const existing = await this.requireEvent(eventId);
    assertPublishReady(existing);
    const toState = resolveTransition(existing.state, "publishEvent");
    return this.applyTransition(eventId, existing, toState, "publishEvent", {
      ...context,
      action: "event.published",
    });
  }

  async pause(
    eventId: string,
    context: TransitionContext,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const existing = await this.requireEvent(eventId);

    if (existing.state === "RegistrationOpen") {
      const updated = await transitionEventState(eventId, existing.state, {
        actorId: context.actorId,
        actorRole: context.actorRole,
        action: "event.paused",
        reasonCode: context.reasonCode,
        reasonText: context.reasonText,
        rulePatch: { registrationPaused: true },
      });
      if (!updated) {
        throw notFound(eventId);
      }
      return toEventResponse(updated);
    }

    if (
      existing.state === "RegistrationClosed" &&
      existing.ruleConfig.registrationPaused
    ) {
      return toEventResponse(existing);
    }

    throw new ApiError({
      code: "INVALID_STATE_TRANSITION",
      message: "Event can only be paused while registration is open.",
      statusCode: 409,
      details: { state: existing.state },
    });
  }

  async openRegistration(
    eventId: string,
    context: TransitionContext,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const existing = await this.requireEvent(eventId);
    const toState = resolveTransition(existing.state, "openRegistrationWindow");
    return this.applyTransition(
      eventId,
      existing,
      toState,
      "openRegistrationWindow",
      {
        ...context,
        action: "event.registration_opened",
        rulePatch: { registrationPaused: false },
      },
    );
  }

  async closeRegistration(
    eventId: string,
    context: TransitionContext,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const existing = await this.requireEvent(eventId);
    const toState = resolveTransition(existing.state, "closeRegistrationWindow");
    return this.applyTransition(
      eventId,
      existing,
      toState,
      "closeRegistrationWindow",
      {
        ...context,
        action: "event.registration_closed",
      },
    );
  }

  async start(
    eventId: string,
    context: TransitionContext,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const existing = await this.requireEvent(eventId);
    const toState = resolveTransition(existing.state, "startEvent");
    return this.applyTransition(eventId, existing, toState, "startEvent", {
      ...context,
      action: "event.started",
    });
  }

  async complete(
    eventId: string,
    context: TransitionContext,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const existing = await this.requireEvent(eventId);
    const toState = resolveTransition(existing.state, "endEvent");
    return this.applyTransition(eventId, existing, toState, "endEvent", {
      ...context,
      action: "event.completed",
    });
  }

  async cancel(
    eventId: string,
    context: TransitionContext,
  ): Promise<ReturnType<typeof toEventResponse>> {
    const existing = await this.requireEvent(eventId);
    if (!context.reasonText?.trim()) {
      throw new ApiError({
        code: "INVALID_INPUT",
        message: "reasonText is required to cancel an event.",
        statusCode: 400,
      });
    }
    const toState = resolveTransition(existing.state, "cancelEvent");
    return this.applyTransition(eventId, existing, toState, "cancelEvent", {
      ...context,
      action: "event.cancelled",
    });
  }

  private async applyTransition(
    eventId: string,
    existing: EventWithConfig,
    toState: ReturnType<typeof resolveTransition>,
    _trigger: EventTransitionTrigger,
    context: TransitionContext & {
      action: string;
      rulePatch?: { registrationPaused?: boolean };
    },
  ): Promise<ReturnType<typeof toEventResponse>> {
    const updated = await transitionEventState(eventId, toState, {
      actorId: context.actorId,
      actorRole: context.actorRole,
      action: context.action,
      reasonCode: context.reasonCode,
      reasonText: context.reasonText,
      rulePatch: context.rulePatch,
    });

    if (!updated) {
      throw notFound(eventId);
    }

    if (updated.state === existing.state && !context.rulePatch) {
      return toEventResponse(updated);
    }

    return toEventResponse(updated);
  }

  private async requireEvent(eventId: string): Promise<EventWithConfig> {
    const event = await findEventById(eventId);
    if (!event) {
      throw notFound(eventId);
    }
    return event;
  }
}

function notFound(eventId: string): ApiError {
  return new ApiError({
    code: "NOT_FOUND",
    message: "Event not found.",
    statusCode: 404,
    details: { eventId },
  });
}

export const eventService = new EventService();
