import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";

import {
  createDraftEvent,
  createRegistrationOpenEvent,
  registerParticipant,
} from "../helpers/event-factory.js";
import {
  type E2EContext,
  type ErrorEnvelope,
  apiRequest,
  assertOk,
  createE2EContext,
  destroyE2EContext,
  futureWindow,
  newIdempotencyKey,
  ORGANIZER_ADMIN_SUB,
  parseJson,
  signDevToken,
} from "../helpers/setup.js";

describe("NFR-14 — event rule config operability", () => {
  let ctx: E2EContext;
  let organizerToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("NFR-14 / FR-02 / FR-03 / TC-NFR-14-001: OrganizerAdmin PATCHes full EventRuleConfig on draft event", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken, {
      capacity: 50,
    });
    const windows = futureWindow(3_600_000);

    const patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: organizerToken,
      payload: {
        ruleConfig: {
          capacity: 80,
          waitlistEnabled: true,
          registrationOpenAt: windows.open,
          registrationCloseAt: windows.close,
          checkinOpenAt: windows.open,
          checkinCloseAt: windows.close,
          feedbackRequired: true,
          feedbackOpenAt: windows.open,
          feedbackCloseAt: windows.close,
        },
      },
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(patchResponse.statusCode, patchResponse.body, "patch rule config");

    const getResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: organizerToken,
    });
    assertOk(getResponse.statusCode, getResponse.body, "get event");
    const event = parseJson<{
      ruleConfig: {
        capacity: number;
        waitlistEnabled: boolean;
        feedbackRequired: boolean;
        registrationOpenAt: string;
      };
    }>(getResponse.body);

    assert.equal(event.ruleConfig.capacity, 80);
    assert.equal(event.ruleConfig.waitlistEnabled, true);
    assert.equal(event.ruleConfig.feedbackRequired, true);
    assert.equal(event.ruleConfig.registrationOpenAt, windows.open);
  });

  it("NFR-14 / FR-02 / TC-NFR-14-002: OrganizerAdmin updates capacity during Draft", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken, {
      capacity: 50,
    });

    const patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: organizerToken,
      payload: { ruleConfig: { capacity: 100 } },
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(patchResponse.statusCode, patchResponse.body, "patch capacity");

    const getResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: organizerToken,
    });
    const event = parseJson<{ ruleConfig: { capacity: number; version: number } }>(
      getResponse.body,
    );
    assert.equal(event.ruleConfig.capacity, 100);
    assert.ok(event.ruleConfig.version >= 2);
  });

  it("NFR-14 / FR-03 / TC-NFR-14-003: toggles waitlist and feedback policy on draft event", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken, {
      waitlistEnabled: false,
      feedbackRequired: false,
    });

    const patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: organizerToken,
      payload: {
        ruleConfig: {
          waitlistEnabled: true,
          feedbackRequired: true,
        },
      },
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(patchResponse.statusCode, patchResponse.body, "toggle policies");

    const getResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: organizerToken,
    });
    const event = parseJson<{
      ruleConfig: { waitlistEnabled: boolean; feedbackRequired: boolean };
    }>(getResponse.body);
    assert.equal(event.ruleConfig.waitlistEnabled, true);
    assert.equal(event.ruleConfig.feedbackRequired, true);
  });

  it("NFR-14 / TC-NFR-14-006: enabling waitlist routes overflow registrations to Waitlisted", async () => {
    const capacity = 1;
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity,
      waitlistEnabled: false,
    });

    const enableWaitlist = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: organizerToken,
      payload: {
        ruleConfig: { waitlistEnabled: true },
        reasonCode: "WAITLIST_ENABLE",
        reasonText: "Expecting higher demand",
      },
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(enableWaitlist.statusCode, enableWaitlist.body, "enable waitlist");

    const firstParticipant = await signDevToken(ctx.app, randomUUID(), "Participant");
    await registerParticipant(ctx.app, firstParticipant, eventId);

    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const overflow = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/registrations`,
      token: participantToken,
      payload: {},
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(overflow.statusCode, 200, overflow.body);
    const body = parseJson<{ state: string }>(overflow.body);
    assert.equal(body.state, "Waitlisted");
  });

  it("NFR-14 / TC-NFR-14-009: post-open critical change succeeds with audit reason", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 10,
    });

    const patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: organizerToken,
      payload: {
        ruleConfig: { capacity: 25 },
        reasonCode: "CAPACITY_INCREASE",
        reasonText: "Venue expansion for NFR-14 scenario",
      },
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(patchResponse.statusCode, patchResponse.body, "post-open patch");

    const auditResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/audit-logs?entityType=EventRuleConfig`,
      token: organizerToken,
    });
    assertOk(auditResponse.statusCode, auditResponse.body, "audit logs");
    const audit = parseJson<{ items: { action: string }[] }>(auditResponse.body);
    assert.ok(
      audit.items.some((entry) => entry.action === "event.rule_config.updated"),
    );
  });

  it("NFR-14 / BR-21 / TC-NFR-14-010: OrganizerStaff cannot PATCH event rule config", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken);
    const staffSub = randomUUID();
    const staffToken = await signDevToken(ctx.app, staffSub, "OrganizerStaff");

    const before = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: organizerToken,
    });
    const original = parseJson<{ ruleConfig: { capacity: number } }>(before.body);

    const patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: staffToken,
      payload: { ruleConfig: { capacity: original.ruleConfig.capacity + 5 } },
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(patchResponse.statusCode, 403, patchResponse.body);

    const after = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: organizerToken,
    });
    const current = parseJson<{ ruleConfig: { capacity: number } }>(after.body);
    assert.equal(current.ruleConfig.capacity, original.ruleConfig.capacity);
  });

  it("NFR-14 / BR-21 / TC-NFR-14-011: Participant cannot PATCH event rule config", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken);
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");

    const patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: participantToken,
      payload: { ruleConfig: { capacity: 999 } },
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(patchResponse.statusCode, 403, patchResponse.body);
  });

  it("NFR-14 / NFR-13 / TC-NFR-14-008: PATCH rejects conflicting check-in window with actionable error", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken);
    const windows = futureWindow(3_600_000);

    const patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: organizerToken,
      payload: {
        ruleConfig: {
          checkinOpenAt: windows.close,
          checkinCloseAt: windows.open,
        },
      },
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(patchResponse.statusCode, 422, patchResponse.body);
    const error = parseJson<ErrorEnvelope>(patchResponse.body);
    assert.equal(error.error.code, "INVALID_INPUT");
    assert.match(error.error.message, /checkin window/i);

    const getResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: organizerToken,
    });
    const event = parseJson<{
      ruleConfig: { checkinOpenAt: string; checkinCloseAt: string };
    }>(getResponse.body);
    assert.notEqual(event.ruleConfig.checkinOpenAt, windows.close);
  });

  it("NFR-14 / TC-NFR-14-012: post-open critical change rejected without mandatory reason", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 10,
    });

    const patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: organizerToken,
      payload: { ruleConfig: { capacity: 20 } },
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(patchResponse.statusCode, 422, patchResponse.body);
    const error = parseJson<ErrorEnvelope>(patchResponse.body);
    assert.equal(
      error.error.code,
      VALIDATION_ERROR_CODES.AUDIT_REQUIRED_FOR_CRITICAL_CHANGE,
    );
  });
});
