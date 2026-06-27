import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import {
  createDraftEvent,
  createRegistrationOpenEvent,
  registerParticipant,
  transitionEvent,
} from "../helpers/event-factory.js";
import {
  type E2EContext,
  type ErrorEnvelope,
  type PaginatedEnvelope,
  apiRequest,
  assertOk,
  createE2EContext,
  defaultTimeWindows,
  destroyE2EContext,
  newIdempotencyKey,
  ORGANIZER_ADMIN_SUB,
  parseJson,
  signDevToken,
} from "../helpers/setup.js";

interface EventListItem {
  eventId: string;
  name: string;
  state: string;
  startAt: string;
}

interface OrganizerRegistrationItem {
  registrationId: string;
  participantId: string;
  state: string;
  waitlistPosition: number | null;
}

interface EligibilityListItem {
  registrationId: string;
  participantId: string;
  eligibility: {
    result: string;
    reasonCode: string;
    reasonText: string;
  };
}

describe("Organizer events — list, filters, and operational APIs (FR-30, FR-01, FR-04)", () => {
  let ctx: E2EContext;
  let organizerToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("TC-FR-30-021 / FR-30: organizer events list supports search, state filter, and sort", async () => {
    const prefix = `Org Events ${randomUUID()}`;
    const draftName = `${prefix} Draft Summit`;
    const openName = `${prefix} Open Workshop`;

    const draft = await createDraftEvent(ctx.app, organizerToken);
    await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${draft.eventId}`,
      token: organizerToken,
      payload: { name: draftName, location: "Draft Hall" },
    });

    const open = await createDraftEvent(ctx.app, organizerToken);
    await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${open.eventId}`,
      token: organizerToken,
      payload: { name: openName, location: "Open Hall" },
    });
    await transitionEvent(ctx.app, organizerToken, open.eventId, "publish");
    await transitionEvent(ctx.app, organizerToken, open.eventId, "open-registration");

    const sortedResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?page=1&pageSize=20&sort=startAt:asc&q=${encodeURIComponent(prefix)}`,
      token: organizerToken,
    });
    assertOk(sortedResponse.statusCode, sortedResponse.body, "sorted events");
    const sorted = parseJson<PaginatedEnvelope<EventListItem>>(sortedResponse.body);
    assert.ok(sorted.items.length >= 2);
    assert.ok(sorted.items.every((item) => item.name.includes(prefix)));

    const draftFilterResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?state=Draft&page=1&pageSize=20&q=${encodeURIComponent(prefix)}`,
      token: organizerToken,
    });
    assertOk(draftFilterResponse.statusCode, draftFilterResponse.body, "Draft filter");
    const draftFiltered = parseJson<PaginatedEnvelope<EventListItem>>(
      draftFilterResponse.body,
    );
    assert.ok(draftFiltered.items.some((item) => item.eventId === draft.eventId));
    assert.ok(draftFiltered.items.every((item) => item.state === "Draft"));

    const searchResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?q=${encodeURIComponent("Draft Summit")}&page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(searchResponse.statusCode, searchResponse.body, "search events");
    const searchBody = parseJson<PaginatedEnvelope<EventListItem>>(searchResponse.body);
    assert.ok(searchBody.items.some((item) => item.eventId === draft.eventId));

    const updatedResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?page=1&pageSize=20&sort=updatedAt:desc&q=${encodeURIComponent(prefix)}`,
      token: organizerToken,
    });
    assertOk(updatedResponse.statusCode, updatedResponse.body, "updatedAt sort");
    parseJson<PaginatedEnvelope<EventListItem>>(updatedResponse.body);
  });

  it("TC-FR-30-008 / FR-30 / AC-18e: organizer filters registrations by Registered and Waitlisted", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 1,
      waitlistEnabled: true,
    });

    const registeredToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const waitlistedToken = await signDevToken(ctx.app, randomUUID(), "Participant");

    const registered = await registerParticipant(ctx.app, registeredToken, eventId);
    assert.equal(registered.state, "Registered");

    const waitlisted = await registerParticipant(ctx.app, waitlistedToken, eventId);
    assert.equal(waitlisted.state, "Waitlisted");

    const registeredResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/registrations?state=Registered&page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(registeredResponse.statusCode, registeredResponse.body, "Registered filter");
    const registeredBody = parseJson<PaginatedEnvelope<OrganizerRegistrationItem>>(
      registeredResponse.body,
    );
    assert.ok(registeredBody.items.length >= 1);
    assert.ok(registeredBody.items.every((item) => item.state === "Registered"));
    assert.ok(
      registeredBody.items.some((item) => item.registrationId === registered.registrationId),
    );

    const waitlistedResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/registrations?state=Waitlisted&page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(waitlistedResponse.statusCode, waitlistedResponse.body, "Waitlisted filter");
    const waitlistedBody = parseJson<PaginatedEnvelope<OrganizerRegistrationItem>>(
      waitlistedResponse.body,
    );
    assert.ok(waitlistedBody.items.length >= 1);
    assert.ok(waitlistedBody.items.every((item) => item.state === "Waitlisted"));
    const waitlistedRow = waitlistedBody.items.find(
      (item) => item.registrationId === waitlisted.registrationId,
    );
    assert.ok(waitlistedRow);
    assert.ok((waitlistedRow.waitlistPosition ?? 0) >= 1);
  });

  it("TC-FR-30-004 / FR-30 / AC-10d: organizer eligibility list includes Eligible, NotEligible, and Revoked", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
      feedbackRequired: true,
    });

    const eligibleToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const notEligibleToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const revokedToken = await signDevToken(ctx.app, randomUUID(), "Participant");

    const eligibleReg = await registerParticipant(ctx.app, eligibleToken, eventId);
    const notEligibleReg = await registerParticipant(ctx.app, notEligibleToken, eventId);
    const revokedReg = await registerParticipant(ctx.app, revokedToken, eventId);

    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
    await transitionEvent(ctx.app, organizerToken, eventId, "start");

    for (const registrationId of [
      eligibleReg.registrationId,
      notEligibleReg.registrationId,
      revokedReg.registrationId,
    ]) {
      const checkinResponse = await apiRequest(ctx.app, {
        method: "POST",
        path: `/events/${eventId}/checkins`,
        token: organizerToken,
        payload: { registrationId },
        idempotencyKey: newIdempotencyKey(),
      });
      assertOk(checkinResponse.statusCode, checkinResponse.body, "staff check-in");
    }

    await transitionEvent(ctx.app, organizerToken, eventId, "complete");

    await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/feedback`,
      token: eligibleToken,
      payload: { answers: { q1: 5 } },
    });
    await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/feedback`,
      token: revokedToken,
      payload: { answers: { q1: 4 } },
    });

    const listResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/eligibility?page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(listResponse.statusCode, listResponse.body, "eligibility list");
    const list = parseJson<PaginatedEnvelope<EligibilityListItem>>(listResponse.body);

    const eligibleRow = list.items.find(
      (row) => row.registrationId === eligibleReg.registrationId,
    );
    const notEligibleRow = list.items.find(
      (row) => row.registrationId === notEligibleReg.registrationId,
    );
    assert.ok(eligibleRow);
    assert.equal(eligibleRow.eligibility.result, "Eligible");
    assert.ok(eligibleRow.eligibility.reasonCode);
    assert.ok(eligibleRow.eligibility.reasonText);

    assert.ok(notEligibleRow);
    assert.equal(notEligibleRow.eligibility.result, "NotEligible");
    assert.ok(notEligibleRow.eligibility.reasonCode);
    assert.ok(notEligibleRow.eligibility.reasonText);

    const revokeResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/eligibility/${revokedReg.registrationId}/revoke`,
      token: organizerToken,
      payload: {
        reasonCode: "POLICY_VIOLATION",
        reasonText: "Revoked for e2e AC-10d coverage",
      },
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(revokeResponse.statusCode, revokeResponse.body, "revoke eligibility");

    const afterRevokeResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/eligibility?page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(afterRevokeResponse.statusCode, afterRevokeResponse.body, "eligibility after revoke");
    const afterRevoke = parseJson<PaginatedEnvelope<EligibilityListItem>>(
      afterRevokeResponse.body,
    );
    const revokedRow = afterRevoke.items.find(
      (row) => row.registrationId === revokedReg.registrationId,
    );
    assert.ok(revokedRow);
    assert.equal(revokedRow.eligibility.result, "Revoked");
    assert.ok(revokedRow.eligibility.reasonCode);
    assert.ok(revokedRow.eligibility.reasonText);
  });

  it("TC-FR-30-022 / FR-30 / AC-10b: invalid eligibility filter returns 400 INVALID_INPUT", async () => {
    const windows = defaultTimeWindows();
    const createResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: "/events",
      token: organizerToken,
      payload: {
        organizationId: "00000000-0000-0000-0000-000000000001",
        name: `Eligibility Filter ${randomUUID()}`,
        startAt: windows.open,
        endAt: windows.close,
        ruleConfig: {
          capacity: 5,
          registrationOpenAt: windows.open,
          registrationCloseAt: windows.close,
          checkinOpenAt: windows.open,
          checkinCloseAt: windows.close,
          feedbackOpenAt: windows.open,
          feedbackCloseAt: windows.close,
        },
      },
    });
    assertOk(createResponse.statusCode, createResponse.body, "create event");
    const { eventId } = parseJson<{ eventId: string }>(createResponse.body);

    const response = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/eligibility?eligibility=InvalidStatus&page=1&pageSize=20`,
      token: organizerToken,
    });
    assert.equal(response.statusCode, 400);
    const body = parseJson<ErrorEnvelope>(response.body);
    assert.equal(body.error.code, "INVALID_INPUT");
  });
});
