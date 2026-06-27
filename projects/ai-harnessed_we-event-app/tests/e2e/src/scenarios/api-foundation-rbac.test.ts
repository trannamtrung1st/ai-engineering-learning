import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import {
  createDraftEvent,
  createRegistrationOpenEvent,
  registerParticipant,
} from "../helpers/event-factory.js";
import {
  type E2EContext,
  DEFAULT_ORG_ID,
  ORGANIZER_ADMIN_SUB,
  apiRequest,
  assertOk,
  createE2EContext,
  defaultTimeWindows,
  destroyE2EContext,
  newIdempotencyKey,
  parseJson,
  signDevToken,
} from "../helpers/setup.js";

/**
 * FR-25 / api-foundation RBAC scenarios from generated test cases.
 */
describe("API foundation RBAC (FR-25, FR-01, FR-20, FR-24, FR-27)", () => {
  let ctx: E2EContext;
  let adminToken: string;
  let participantToken: string;
  const participantSub = randomUUID();

  before(async () => {
    ctx = await createE2EContext();
    adminToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
    participantToken = await signDevToken(ctx.app, participantSub, "Participant");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("FR-01: OrganizerAdmin can create event draft via POST /events", async () => {
    const windows = defaultTimeWindows();
    const response = await apiRequest(ctx.app, {
      method: "POST",
      path: "/events",
      token: adminToken,
      payload: {
        organizationId: DEFAULT_ORG_ID,
        name: `RBAC Draft ${randomUUID()}`,
        description: "FR-01 create draft",
        location: "Room RBAC",
        startAt: windows.open,
        endAt: windows.close,
        ruleConfig: {
          capacity: 10,
          waitlistEnabled: false,
          registrationOpenAt: windows.open,
          registrationCloseAt: windows.close,
          checkinOpenAt: windows.open,
          checkinCloseAt: windows.close,
          feedbackRequired: true,
          feedbackOpenAt: windows.open,
          feedbackCloseAt: windows.close,
        },
      },
    });

    assertOk(response.statusCode, response.body, "FR-01 create event");
    const body = parseJson<{ eventId: string; state: string }>(response.body);
    assert.ok(body.eventId);
    assert.equal(body.state, "Draft");
  });

  it("FR-20: OrganizerStaff denied eligibility revocation override", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, adminToken, {
      capacity: 5,
    });
    const { registrationId } = await registerParticipant(
      ctx.app,
      participantToken,
      eventId,
    );

    const staffSub = randomUUID();
    const staffToken = await signDevToken(ctx.app, staffSub, "OrganizerStaff", [
      eventId,
    ]);

    const response = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/eligibility/${registrationId}/revoke`,
      token: staffToken,
      payload: {
        reasonCode: "POLICY",
        reasonText: "Staff must not revoke eligibility.",
      },
      idempotencyKey: newIdempotencyKey(),
    });

    assert.equal(response.statusCode, 403);
    const body = parseJson<{ error: { code: string } }>(response.body);
    assert.equal(body.error.code, "FORBIDDEN");
  });

  it("FR-24: Participant cannot export event operational data", async () => {
    const { eventId } = await createDraftEvent(ctx.app, adminToken);

    const response = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/export?type=eligibility`,
      token: participantToken,
    });

    assert.equal(response.statusCode, 403);
    const body = parseJson<{ error: { code: string } }>(response.body);
    assert.equal(body.error.code, "FORBIDDEN");
  });

  it("FR-27: OrganizerStaff denied staff operations on unassigned event", async () => {
    const assignedEventId = (
      await createRegistrationOpenEvent(ctx.app, adminToken, { capacity: 5 })
    ).eventId;
    const unassignedEventId = (
      await createRegistrationOpenEvent(ctx.app, adminToken, { capacity: 5 })
    ).eventId;
    const { registrationId } = await registerParticipant(
      ctx.app,
      participantToken,
      unassignedEventId,
    );

    const staffSub = randomUUID();
    const staffToken = await signDevToken(ctx.app, staffSub, "OrganizerStaff", [
      assignedEventId,
    ]);

    const listDenied = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${unassignedEventId}/registrations?page=1&pageSize=20`,
      token: staffToken,
    });
    assert.equal(listDenied.statusCode, 403);
    assert.equal(
      parseJson<{ error: { code: string } }>(listDenied.body).error.code,
      "FORBIDDEN",
    );

    const checkinDenied = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${unassignedEventId}/checkins`,
      token: staffToken,
      payload: { registrationId },
      idempotencyKey: newIdempotencyKey(),
    });
    assert.equal(checkinDenied.statusCode, 403);
    assert.equal(
      parseJson<{ error: { code: string } }>(checkinDenied.body).error.code,
      "FORBIDDEN",
    );
  });
});
