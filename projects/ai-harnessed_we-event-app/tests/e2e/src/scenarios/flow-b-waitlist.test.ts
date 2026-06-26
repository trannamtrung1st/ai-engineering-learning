import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";

import {
  createRegistrationOpenEvent,
  registerParticipant,
  transitionEvent,
} from "../helpers/event-factory.js";
import {
  type E2EContext,
  type ErrorEnvelope,
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
 * Flow B (testing plan §6): full event → waitlist entry → cancellation →
 * auto promotion → check-in.
 */
describe("Flow B — waitlist promotion (AC-02, AC-03, FR-11, BR-07, FR-12)", () => {
  let ctx: E2EContext;
  let organizerToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("AC-02: waitlists participant when event is full", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 1,
      waitlistEnabled: true,
    });

    const firstToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const secondToken = await signDevToken(ctx.app, randomUUID(), "Participant");

    const first = await registerParticipant(ctx.app, firstToken, eventId);
    assert.equal(first.state, "Registered");

    const waitlistResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/registrations`,
      token: secondToken,
      payload: {},
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(waitlistResponse.statusCode, waitlistResponse.body, "AC-02 waitlist");
    const waitlisted = parseJson<{ state: string; waitlistPosition: number }>(
      waitlistResponse.body,
    );
    assert.equal(waitlisted.state, "Waitlisted");
    assert.equal(waitlisted.waitlistPosition, 1);
  });

  it("AC-03: blocks duplicate registration for same participant", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const participantSub = randomUUID();
    const token = await signDevToken(ctx.app, participantSub, "Participant");

    await registerParticipant(ctx.app, token, eventId);

    const duplicateResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/registrations`,
      token,
      payload: {},
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(duplicateResponse.statusCode, 409, duplicateResponse.body);
    const error = parseJson<ErrorEnvelope>(duplicateResponse.body);
    assert.equal(
      error.error.code,
      VALIDATION_ERROR_CODES.REGISTRATION_DUPLICATE_ACTIVE,
    );
  });

  it("promotes waitlisted participant after cancellation and allows check-in", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 1,
      waitlistEnabled: true,
    });

    const holderSub = randomUUID();
    const promotedSub = randomUUID();
    const holderToken = await signDevToken(ctx.app, holderSub, "Participant");
    const promotedToken = await signDevToken(ctx.app, promotedSub, "Participant");

    const holder = await registerParticipant(ctx.app, holderToken, eventId);
    const waitlisted = await registerParticipant(ctx.app, promotedToken, eventId);
    assert.equal(waitlisted.state, "Waitlisted");

    const cancelResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/registrations/${holder.registrationId}/cancel`,
      token: holderToken,
      payload: {},
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(cancelResponse.statusCode, cancelResponse.body, "FR-11 / BR-07 cancel holder");
    const cancelBody = parseJson<{
      promoted: { registrationId: string; state: string } | null;
    }>(cancelResponse.body);
    assert.ok(cancelBody.promoted);
    assert.equal(cancelBody.promoted.registrationId, waitlisted.registrationId);
    assert.equal(cancelBody.promoted.state, "Registered");

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/self-checkin`,
      token: promotedToken,
      payload: {},
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(checkinResponse.statusCode, checkinResponse.body, "promoted check-in");
    const checkin = parseJson<{ registrationState: string }>(checkinResponse.body);
    assert.equal(checkin.registrationState, "CheckedIn");
  });
});
