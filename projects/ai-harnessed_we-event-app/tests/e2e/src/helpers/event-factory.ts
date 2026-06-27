import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";

import {
  DEFAULT_ORG_ID,
  apiRequest,
  assertOk,
  defaultTimeWindows,
  newIdempotencyKey,
  parseJson,
} from "./setup.js";

export interface EventFactoryOptions {
  capacity?: number;
  waitlistEnabled?: boolean;
  feedbackRequired?: boolean;
  checkinOpenAt?: string;
  checkinCloseAt?: string;
  feedbackOpenAt?: string;
  feedbackCloseAt?: string;
  selfCheckinEnabled?: boolean;
}

export interface CreatedEvent {
  eventId: string;
}

export async function createDraftEvent(
  app: FastifyInstance,
  organizerToken: string,
  options: EventFactoryOptions = {},
): Promise<CreatedEvent> {
  const windows = defaultTimeWindows();
  const response = await apiRequest(app, {
    method: "POST",
    path: "/events",
    token: organizerToken,
    payload: {
      organizationId: DEFAULT_ORG_ID,
      name: `E2E Event ${randomUUID()}`,
      description: "End-to-end scenario fixture",
      location: "Room E2E",
      startAt: windows.open,
      endAt: windows.close,
      ruleConfig: {
        capacity: options.capacity ?? 10,
        waitlistEnabled: options.waitlistEnabled ?? false,
        registrationOpenAt: windows.open,
        registrationCloseAt: windows.close,
        checkinOpenAt: options.checkinOpenAt ?? windows.open,
        checkinCloseAt: options.checkinCloseAt ?? windows.close,
        feedbackRequired: options.feedbackRequired ?? true,
        feedbackOpenAt: options.feedbackOpenAt ?? windows.open,
        feedbackCloseAt: options.feedbackCloseAt ?? windows.close,
        selfCheckinEnabled: options.selfCheckinEnabled ?? true,
      },
    },
  });

  assertOk(response.statusCode, response.body, "create event");
  const body = parseJson<{ eventId: string }>(response.body);
  assert.ok(body.eventId);
  return { eventId: body.eventId };
}

type TransitionPath =
  | "publish"
  | "open-registration"
  | "close-registration"
  | "start"
  | "complete";

export async function transitionEvent(
  app: FastifyInstance,
  organizerToken: string,
  eventId: string,
  transition: TransitionPath,
  body?: { reasonCode?: string; reasonText?: string },
): Promise<void> {
  const response = await apiRequest(app, {
    method: "POST",
    path: `/events/${eventId}/${transition}`,
    token: organizerToken,
    payload: body,
    idempotencyKey: newIdempotencyKey(),
  });
  assertOk(response.statusCode, response.body, `transition ${transition}`);
}

export async function createRegistrationOpenEvent(
  app: FastifyInstance,
  organizerToken: string,
  options: EventFactoryOptions = {},
): Promise<CreatedEvent> {
  const created = await createDraftEvent(app, organizerToken, options);
  await transitionEvent(app, organizerToken, created.eventId, "publish");
  await transitionEvent(app, organizerToken, created.eventId, "open-registration");
  return created;
}

export async function registerParticipant(
  app: FastifyInstance,
  participantToken: string,
  eventId: string,
): Promise<{ registrationId: string; state: string }> {
  const response = await apiRequest(app, {
    method: "POST",
    path: `/events/${eventId}/registrations`,
    token: participantToken,
    payload: {},
    idempotencyKey: newIdempotencyKey(),
  });
  assertOk(response.statusCode, response.body, "register participant");
  const body = parseJson<{ registrationId: string; state: string }>(response.body);
  return body;
}
