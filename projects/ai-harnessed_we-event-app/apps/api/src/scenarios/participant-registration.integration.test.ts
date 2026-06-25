import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import type { FastifyInstance } from "fastify";

import { buildApp } from "../index.js";
import { ensureIdempotencySchema } from "../idempotency/index.js";
import {
  createEvent,
  ensureEventSchema,
  transitionEventState,
} from "../modules/event/repository.js";
import type { EventWithConfig } from "../modules/event/types.js";
import { ensureRegistrationSchema } from "../modules/registration/repository.js";
import {
  ensureTestOrganizerAdmin,
  ensureTestParticipant,
} from "../test-helpers/participant-user.js";

const DEV_PARTICIPANT_SUB = "participant-1";
const ORG_ID = "00000000-0000-0000-0000-000000000001";
const ORGANIZER_ID = "00000000-0000-0000-0000-000000000099";

function defaultWindows() {
  const now = Date.now();
  return {
    open: new Date(now - 3_600_000).toISOString(),
    close: new Date(now + 86_400_000).toISOString(),
  };
}

async function createRegistrationOpenEvent(options: {
  capacity: number;
}): Promise<EventWithConfig> {
  const windows = defaultWindows();
  const draft = await createEvent(
    {
      name: `Scenario Event ${randomUUID()}`,
      startAt: windows.open,
      endAt: windows.close,
      ruleConfig: {
        capacity: options.capacity,
        waitlistEnabled: false,
        registrationOpenAt: windows.open,
        registrationCloseAt: windows.close,
        checkinOpenAt: windows.open,
        checkinCloseAt: windows.close,
        feedbackOpenAt: windows.open,
        feedbackCloseAt: windows.close,
      },
    },
    ORGANIZER_ID,
    "OrganizerAdmin",
    ORG_ID,
  );

  const transitionContext = {
    actorId: ORGANIZER_ID,
    actorRole: "OrganizerAdmin",
    action: "test.transition",
  };

  await transitionEventState(draft.id, "Published", {
    ...transitionContext,
    action: "event.published",
  });

  const open = await transitionEventState(draft.id, "RegistrationOpen", {
    ...transitionContext,
    action: "event.registration_opened",
  });

  if (!open) {
    throw new Error("Failed to open registration for scenario event");
  }
  return open;
}

async function signDevToken(
  app: FastifyInstance,
  sub: string,
  role: string,
): Promise<string> {
  const response = await app.inject({
    method: "POST",
    url: "/api/v1/dev/token",
    payload: { sub, role },
  });
  assert.equal(response.statusCode, 200, response.body);
  return (JSON.parse(response.body) as { token: string }).token;
}

describe("participant registration HTTP scenario", () => {
  let app: FastifyInstance;
  let eventId: string;
  let participantToken: string;

  before(async () => {
    process.env.DATABASE_URL ??=
      "postgresql://we_event:we_event@localhost:5432/we_event";
    process.env.JWT_SECRET ??= "test-jwt-secret";
    process.env.DEV_AUTH_ENABLED = "true";

    ({ app } = await buildApp());
    await ensureEventSchema();
    await ensureRegistrationSchema();
    await ensureIdempotencySchema();
    await ensureTestOrganizerAdmin(ORGANIZER_ID);
    await ensureTestParticipant(DEV_PARTICIPANT_SUB);

    const event = await createRegistrationOpenEvent({ capacity: 5 });
    eventId = event.id;
    participantToken = await signDevToken(app, DEV_PARTICIPANT_SUB, "Participant");
  });

  after(async () => {
    await app.close();
  });

  it("FR-10: GET /events/:eventId/registration-status returns 200 with null before register", async () => {
    const response = await app.inject({
      method: "GET",
      url: `/api/v1/events/${eventId}/registration-status`,
      headers: { authorization: `Bearer ${participantToken}` },
    });

    assert.equal(response.statusCode, 200, response.body);
    const body = JSON.parse(response.body) as { registration: unknown };
    assert.equal(body.registration, null);
  });

  it("AC-01: participant can register and registration-status reflects Registered", async () => {
    const registerResponse = await app.inject({
      method: "POST",
      url: `/api/v1/events/${eventId}/registrations`,
      headers: {
        authorization: `Bearer ${participantToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    assert.equal(registerResponse.statusCode, 200, registerResponse.body);
    const registered = JSON.parse(registerResponse.body) as { state: string };
    assert.equal(registered.state, "Registered");

    const statusResponse = await app.inject({
      method: "GET",
      url: `/api/v1/events/${eventId}/registration-status`,
      headers: { authorization: `Bearer ${participantToken}` },
    });

    assert.equal(statusResponse.statusCode, 200, statusResponse.body);
    const status = JSON.parse(statusResponse.body) as {
      registration: { state: string } | null;
    };
    assert.ok(status.registration);
    assert.equal(status.registration.state, "Registered");
  });
});
