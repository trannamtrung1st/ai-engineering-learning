import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import {
  createDraftEvent,
  transitionEvent,
} from "../helpers/event-factory.js";
import {
  type E2EContext,
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
 * Flow A (testing plan §6): draft → publish → open registration → register →
 * check-in → feedback → eligibility.
 */
describe("Flow A — full participant lifecycle (AC-01, AC-05, AC-08, AC-09, FR-13, FR-15, FR-19, BR-15, BR-18, BR-19, AC-15)", () => {
  let ctx: E2EContext;
  let organizerToken: string;
  let participantToken: string;
  const participantSub = randomUUID();

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
    participantToken = await signDevToken(ctx.app, participantSub, "Participant");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("runs draft through eligibility evaluation", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken, {
      capacity: 5,
      feedbackRequired: true,
    });

    await transitionEvent(ctx.app, organizerToken, eventId, "publish");
    await transitionEvent(ctx.app, organizerToken, eventId, "open-registration");

    const registerResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/registrations`,
      token: participantToken,
      payload: {},
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(registerResponse.statusCode, registerResponse.body, "AC-01 register");
    const registration = parseJson<{ state: string; registrationId: string }>(
      registerResponse.body,
    );
    assert.equal(registration.state, "Registered");

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    const checkinResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/self-checkin`,
      token: participantToken,
      payload: {},
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(checkinResponse.statusCode, checkinResponse.body, "AC-05 / FR-13 / FR-15 / FR-16 check-in");
    const checkin = parseJson<{ checkinAt: string; registrationState: string }>(
      checkinResponse.body,
    );
    assert.equal(checkin.registrationState, "CheckedIn");
    assert.ok(checkin.checkinAt);

    await transitionEvent(ctx.app, organizerToken, eventId, "complete");

    const feedbackResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/feedback`,
      token: participantToken,
      payload: { answers: { q1: 5, q2: "Excellent session" } },
    });
    assertOk(feedbackResponse.statusCode, feedbackResponse.body, "AC-08 / FR-19 / BR-15 feedback");
    const feedback = parseJson<{ submittedAt: string }>(feedbackResponse.body);
    assert.ok(feedback.submittedAt);

    const eligibilityResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/eligibility/me`,
      token: participantToken,
    });
    assertOk(eligibilityResponse.statusCode, eligibilityResponse.body, "AC-09 eligibility");
    const eligibility = parseJson<{
      result: string;
      reasonCode: string;
      reasonText: string;
    }>(eligibilityResponse.body);
    assert.equal(eligibility.result, "Eligible");
    assert.ok(eligibility.reasonCode);
    assert.ok(eligibility.reasonText);

    const organizerListResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/eligibility?page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(
      organizerListResponse.statusCode,
      organizerListResponse.body,
      "TC-AC-10-004 / FR-21 / BR-18 / BR-19 organizer eligibility list",
    );
    const organizerList = parseJson<{
      items: Array<{
        registrationId: string;
        eligibility: { result: string; reasonCode: string; reasonText: string };
      }>;
    }>(organizerListResponse.body);
    const listEntry = organizerList.items.find(
      (row) => row.registrationId === registration.registrationId,
    );
    assert.ok(listEntry);
    assert.equal(listEntry.eligibility.result, "Eligible");
    assert.ok(listEntry.eligibility.reasonCode);
    assert.ok(listEntry.eligibility.reasonText);
  });
});
