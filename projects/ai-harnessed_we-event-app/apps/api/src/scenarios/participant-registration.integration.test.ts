import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import type { FastifyInstance } from "fastify";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";

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
  waitlistEnabled?: boolean;
}): Promise<EventWithConfig> {
  const windows = defaultWindows();
  const draft = await createEvent(
    {
      name: `Scenario Event ${randomUUID()}`,
      startAt: windows.open,
      endAt: windows.close,
      ruleConfig: {
        capacity: options.capacity,
        waitlistEnabled: options.waitlistEnabled ?? false,
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
    actorRole: "OrganizerAdmin" as const,
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
  const participantSub = `scenario-participant-${randomUUID().slice(0, 8)}`;

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
    await ensureTestParticipant(participantSub);

    const event = await createRegistrationOpenEvent({ capacity: 5 });
    eventId = event.id;
    participantToken = await signDevToken(app, participantSub, "Participant");
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

describe("waitlist registration HTTP scenarios (AC-02, AC-02a)", () => {
  let app: FastifyInstance;

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
  });

  after(async () => {
    await app.close();
  });

  it("TC-AC-02-002 / TC-AC-02-005 / AC-02a: POST registrations returns Waitlisted when event is full", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });
    const firstSub = `waitlist-first-${randomUUID().slice(0, 8)}`;
    const secondSub = `waitlist-second-${randomUUID().slice(0, 8)}`;
    await ensureTestParticipant(firstSub);
    await ensureTestParticipant(secondSub);

    const firstToken = await signDevToken(app, firstSub, "Participant");
    const secondToken = await signDevToken(app, secondSub, "Participant");

    const firstRegister = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${firstToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    assert.equal(firstRegister.statusCode, 200, firstRegister.body);
    assert.equal(
      (JSON.parse(firstRegister.body) as { state: string }).state,
      "Registered",
    );

    const waitlistRegister = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${secondToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    assert.equal(waitlistRegister.statusCode, 200, waitlistRegister.body);
    const waitlisted = JSON.parse(waitlistRegister.body) as {
      state: string;
      waitlistPosition: number;
    };
    assert.equal(waitlisted.state, "Waitlisted");
    assert.ok(waitlisted.waitlistPosition >= 1);

    const statusResponse = await app.inject({
      method: "GET",
      url: `/api/v1/events/${event.id}/registration-status`,
      headers: { authorization: `Bearer ${secondToken}` },
    });
    assert.equal(statusResponse.statusCode, 200, statusResponse.body);
    const status = JSON.parse(statusResponse.body) as {
      registration: { state: string; waitlistPosition: number } | null;
    };
    assert.ok(status.registration);
    assert.equal(status.registration.state, "Waitlisted");
    assert.equal(status.registration.waitlistPosition, waitlisted.waitlistPosition);
  });

  it("TC-AC-02-008 / AC-02a: boundary capacity assigns last entrant to waitlist", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 2,
      waitlistEnabled: true,
    });
    const subs = ["p1", "p2", "p3"].map(
      (label) => `boundary-${label}-${randomUUID().slice(0, 8)}`,
    );
    for (const sub of subs) {
      await ensureTestParticipant(sub);
    }
    const tokens = await Promise.all(
      subs.map((sub) => signDevToken(app, sub, "Participant")),
    );

    const first = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${tokens[0]}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    const second = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${tokens[1]}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    const third = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${tokens[2]}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    assert.equal(
      (JSON.parse(first.body) as { state: string }).state,
      "Registered",
    );
    assert.equal(
      (JSON.parse(second.body) as { state: string }).state,
      "Registered",
    );
    const thirdBody = JSON.parse(third.body) as {
      state: string;
      waitlistPosition: number;
    };
    assert.equal(thirdBody.state, "Waitlisted");
    assert.equal(thirdBody.waitlistPosition, 1);
  });

  it("TC-FR-10-003 / FR-10a: registration-status reflects Waitlisted with queue position", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });
    const firstSub = `status-first-${randomUUID().slice(0, 8)}`;
    const secondSub = `status-second-${randomUUID().slice(0, 8)}`;
    await ensureTestParticipant(firstSub);
    await ensureTestParticipant(secondSub);

    const firstToken = await signDevToken(app, firstSub, "Participant");
    const secondToken = await signDevToken(app, secondSub, "Participant");

    await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${firstToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    const registerResponse = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${secondToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    const registered = JSON.parse(registerResponse.body) as {
      state: string;
      waitlistPosition: number;
    };

    const statusResponse = await app.inject({
      method: "GET",
      url: `/api/v1/events/${event.id}/registration-status`,
      headers: { authorization: `Bearer ${secondToken}` },
    });

    assert.equal(statusResponse.statusCode, 200, statusResponse.body);
    const status = JSON.parse(statusResponse.body) as {
      registration: { state: string; waitlistPosition: number } | null;
    };
    assert.ok(status.registration);
    assert.equal(status.registration.state, "Waitlisted");
    assert.equal(
      status.registration.waitlistPosition,
      registered.waitlistPosition,
    );
  });

  it("TC-AC-02-010 / AC-02b: full event without waitlist rejects registration", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: false,
    });
    const firstSub = `reject-first-${randomUUID().slice(0, 8)}`;
    const secondSub = `reject-second-${randomUUID().slice(0, 8)}`;
    await ensureTestParticipant(firstSub);
    await ensureTestParticipant(secondSub);

    const firstToken = await signDevToken(app, firstSub, "Participant");
    const secondToken = await signDevToken(app, secondSub, "Participant");

    await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${firstToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    const rejectResponse = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${secondToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    assert.equal(rejectResponse.statusCode, 422, rejectResponse.body);
    const body = JSON.parse(rejectResponse.body) as { error: { code: string } };
    assert.equal(
      body.error.code,
      VALIDATION_ERROR_CODES.REGISTRATION_REJECTED_FULL,
    );
  });

  it("TC-AC-04-010 / AC-02b: full event without waitlist keeps Registered count at capacity", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 2,
      waitlistEnabled: false,
    });
    const participantSubs = ["a", "b", "c"].map(
      (label) => `full-${label}-${randomUUID().slice(0, 8)}`,
    );
    for (const sub of participantSubs) {
      await ensureTestParticipant(sub);
    }
    const tokens = await Promise.all(
      participantSubs.map((sub) => signDevToken(app, sub, "Participant")),
    );
    const organizerToken = await signDevToken(app, ORGANIZER_ID, "OrganizerAdmin");

    for (let index = 0; index < 2; index += 1) {
      const response = await app.inject({
        method: "POST",
        url: `/api/v1/events/${event.id}/registrations`,
        headers: {
          authorization: `Bearer ${tokens[index]}`,
          "idempotency-key": randomUUID(),
        },
        payload: {},
      });
      assert.equal(response.statusCode, 200, response.body);
    }

    const rejectResponse = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${tokens[2]}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    assert.equal(rejectResponse.statusCode, 422, rejectResponse.body);

    const listResponse = await app.inject({
      method: "GET",
      url: `/api/v1/events/${event.id}/registrations?state=Registered`,
      headers: { authorization: `Bearer ${organizerToken}` },
    });
    assert.equal(listResponse.statusCode, 200, listResponse.body);
    const list = JSON.parse(listResponse.body) as { total: number };
    assert.equal(list.total, 2);
  });

  it("TC-AC-02-014 / AC-02c: cancel Registered participant promotes FIFO waitlisted entrant", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });
    const registeredSub = `promote-reg-${randomUUID().slice(0, 8)}`;
    const waitlistedSub = `promote-wl-${randomUUID().slice(0, 8)}`;
    await ensureTestParticipant(registeredSub);
    await ensureTestParticipant(waitlistedSub);

    const registeredToken = await signDevToken(app, registeredSub, "Participant");
    const waitlistedToken = await signDevToken(app, waitlistedSub, "Participant");

    const registeredResponse = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${registeredToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    const registered = JSON.parse(registeredResponse.body) as {
      registrationId: string;
    };

    await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${waitlistedToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    const cancelResponse = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations/${registered.registrationId}/cancel`,
      headers: {
        authorization: `Bearer ${registeredToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    assert.equal(cancelResponse.statusCode, 200, cancelResponse.body);

    const statusResponse = await app.inject({
      method: "GET",
      url: `/api/v1/events/${event.id}/registration-status`,
      headers: { authorization: `Bearer ${waitlistedToken}` },
    });
    const status = JSON.parse(statusResponse.body) as {
      registration: { state: string; waitlistPosition: number | null } | null;
    };
    assert.ok(status.registration);
    assert.equal(status.registration.state, "Registered");
    assert.equal(status.registration.waitlistPosition, null);
  });

  it("TC-AC-03-012 / BR-04b: duplicate registration blocked after waitlist entry", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });
    const firstSub = `dup-first-${randomUUID().slice(0, 8)}`;
    const waitlistedSub = `dup-wl-${randomUUID().slice(0, 8)}`;
    await ensureTestParticipant(firstSub);
    await ensureTestParticipant(waitlistedSub);

    const firstToken = await signDevToken(app, firstSub, "Participant");
    const waitlistedToken = await signDevToken(app, waitlistedSub, "Participant");

    await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${firstToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    const firstWaitlist = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${waitlistedToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    const original = JSON.parse(firstWaitlist.body) as {
      registrationId: string;
      waitlistPosition: number;
    };

    const duplicate = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${waitlistedToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    assert.equal(duplicate.statusCode, 409, duplicate.body);
    const duplicateBody = JSON.parse(duplicate.body) as { error: { code: string } };
    assert.equal(
      duplicateBody.error.code,
      VALIDATION_ERROR_CODES.REGISTRATION_DUPLICATE_ACTIVE,
    );

    const statusResponse = await app.inject({
      method: "GET",
      url: `/api/v1/events/${event.id}/registration-status`,
      headers: { authorization: `Bearer ${waitlistedToken}` },
    });
    const status = JSON.parse(statusResponse.body) as {
      registration: {
        registrationId: string;
        state: string;
        waitlistPosition: number;
      } | null;
    };
    assert.ok(status.registration);
    assert.equal(status.registration.registrationId, original.registrationId);
    assert.equal(status.registration.state, "Waitlisted");
    assert.equal(status.registration.waitlistPosition, original.waitlistPosition);
  });

  it("TC-AC-02-012 / FR-30a: organizer GET waitlist includes waitlisted participant with position", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });
    const registeredSub = `org-reg-${randomUUID().slice(0, 8)}`;
    const waitlistedSub = `org-wl-${randomUUID().slice(0, 8)}`;
    await ensureTestParticipant(registeredSub);
    await ensureTestParticipant(waitlistedSub);

    const registeredToken = await signDevToken(app, registeredSub, "Participant");
    const waitlistedToken = await signDevToken(app, waitlistedSub, "Participant");
    const organizerToken = await signDevToken(app, ORGANIZER_ID, "OrganizerAdmin");

    await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${registeredToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    const waitlistRegister = await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${waitlistedToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });
    const waitlisted = JSON.parse(waitlistRegister.body) as {
      registrationId: string;
      waitlistPosition: number;
    };

    const waitlistResponse = await app.inject({
      method: "GET",
      url: `/api/v1/events/${event.id}/waitlist?page=1&pageSize=20&sort=position:asc`,
      headers: { authorization: `Bearer ${organizerToken}` },
    });
    assert.equal(waitlistResponse.statusCode, 200, waitlistResponse.body);

    const waitlist = JSON.parse(waitlistResponse.body) as {
      items: Array<{
        registrationId: string;
        position: number;
        state: string;
      }>;
      total: number;
    };
    assert.equal(waitlist.total, 1);
    assert.equal(waitlist.items[0]?.registrationId, waitlisted.registrationId);
    assert.equal(waitlist.items[0]?.position, waitlisted.waitlistPosition);
    assert.equal(waitlist.items[0]?.state, "Waitlisted");
  });

  it("TC-AC-02-013 / FR-30a: organizer waitlist FIFO order preserved across paginated pages", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });
    const registeredSub = `paginate-reg-${randomUUID().slice(0, 8)}`;
    await ensureTestParticipant(registeredSub);
    const registeredToken = await signDevToken(app, registeredSub, "Participant");
    const organizerToken = await signDevToken(app, ORGANIZER_ID, "OrganizerAdmin");

    await app.inject({
      method: "POST",
      url: `/api/v1/events/${event.id}/registrations`,
      headers: {
        authorization: `Bearer ${registeredToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    const waitlistCount = 21;
    for (let index = 0; index < waitlistCount; index += 1) {
      const sub = `paginate-wl-${index}-${randomUUID().slice(0, 8)}`;
      await ensureTestParticipant(sub);
      const token = await signDevToken(app, sub, "Participant");
      const response = await app.inject({
        method: "POST",
        url: `/api/v1/events/${event.id}/registrations`,
        headers: {
          authorization: `Bearer ${token}`,
          "idempotency-key": randomUUID(),
        },
        payload: {},
      });
      assert.equal(response.statusCode, 200, response.body);
      const body = JSON.parse(response.body) as { waitlistPosition: number };
      assert.equal(body.waitlistPosition, index + 1);
    }

    const page1Response = await app.inject({
      method: "GET",
      url: `/api/v1/events/${event.id}/waitlist?page=1&pageSize=20&sort=position:asc`,
      headers: { authorization: `Bearer ${organizerToken}` },
    });
    assert.equal(page1Response.statusCode, 200, page1Response.body);
    const page1 = JSON.parse(page1Response.body) as {
      items: Array<{ position: number }>;
      total: number;
      totalPages: number;
    };
    assert.equal(page1.total, waitlistCount);
    assert.equal(page1.totalPages, 2);
    assert.equal(page1.items.length, 20);
    assert.equal(page1.items[0]?.position, 1);
    assert.equal(page1.items[19]?.position, 20);

    const page2Response = await app.inject({
      method: "GET",
      url: `/api/v1/events/${event.id}/waitlist?page=2&pageSize=20&sort=position:asc`,
      headers: { authorization: `Bearer ${organizerToken}` },
    });
    assert.equal(page2Response.statusCode, 200, page2Response.body);
    const page2 = JSON.parse(page2Response.body) as {
      items: Array<{ position: number }>;
    };
    assert.equal(page2.items.length, 1);
    assert.equal(page2.items[0]?.position, 21);
  });
});
