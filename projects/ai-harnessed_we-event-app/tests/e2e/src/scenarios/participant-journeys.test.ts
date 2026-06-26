import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import {
  createRegistrationOpenEvent,
  registerParticipant,
  transitionEvent,
} from "../helpers/event-factory.js";
import {
  type E2EContext,
  type PaginatedEnvelope,
  apiRequest,
  assertOk,
  createE2EContext,
  destroyE2EContext,
  newIdempotencyKey,
  ORGANIZER_ADMIN_SUB,
  parseJson,
  signDevToken,
} from "../helpers/setup.js";

/**
 * Participant journey API contracts for web-participant-journeys slice:
 * registration-status after attendance, paginated my registrations (FR-28, FR-29).
 */
describe("Participant journeys — registration status and my registrations (FR-10, FR-28, FR-29, FR-31, AC-15)", () => {
  let ctx: E2EContext;
  let organizerToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("registration-status returns Attended after event completion for feedback UI (AC-08)", async () => {
    const participantSub = randomUUID();
    const participantToken = await signDevToken(ctx.app, participantSub, "Participant");

    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/checkins`,
      token: organizerToken,
      payload: { registrationId: registered.registrationId },
      idempotencyKey: newIdempotencyKey(),
    });

    await transitionEvent(ctx.app, organizerToken, eventId, "complete");

    const statusResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/registration-status`,
      token: participantToken,
    });
    assertOk(statusResponse.statusCode, statusResponse.body, "registration-status");
    const status = parseJson<{ registration: { state: string } | null }>(
      statusResponse.body,
    );
    assert.ok(status.registration);
    assert.equal(status.registration.state, "Attended");
  });

  it("GET /me/registrations returns paginated envelope with gating context (FR-31, NFR-16)", async () => {
    const participantSub = randomUUID();
    const participantToken = await signDevToken(ctx.app, participantSub, "Participant");

    const eventA = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const eventB = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });

    await registerParticipant(ctx.app, participantToken, eventA.eventId);
    await registerParticipant(ctx.app, participantToken, eventB.eventId);

    const pageResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: "/me/registrations?page=1&pageSize=1",
      token: participantToken,
    });
    assertOk(pageResponse.statusCode, pageResponse.body, "my registrations page 1");
    const page = parseJson<
      PaginatedEnvelope<{
        eventId: string;
        eventState: string;
        checkinOpenAt: string;
        feedbackOpenAt: string;
      }>
    >(pageResponse.body);

    assert.equal(page.page, 1);
    assert.equal(page.pageSize, 1);
    assert.equal(page.total, 2);
    assert.equal(page.totalPages, 2);
    assert.equal(page.items.length, 1);
    assert.ok(page.items[0]?.eventState);
    assert.ok(page.items[0]?.checkinOpenAt);
    assert.ok(page.items[0]?.feedbackOpenAt);
  });
});
