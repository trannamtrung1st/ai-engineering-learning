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
  defaultTimeWindows,
  destroyE2EContext,
  newIdempotencyKey,
  ORGANIZER_ADMIN_SUB,
  parseJson,
  signDevToken,
} from "../helpers/setup.js";

describe("Acceptance matrix — capacity, check-in, attendance, eligibility, pagination (NFR-02, NFR-04, AC-15)", () => {
  let ctx: E2EContext;
  let organizerToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("AC-04: concurrent registrations never exceed capacity", async () => {
    const capacity = 3;
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity,
      waitlistEnabled: true,
    });

    const attempts = 10;
    const responses = await Promise.all(
      Array.from({ length: attempts }, async (_, index) => {
        const token = await signDevToken(
          ctx.app,
          randomUUID(),
          "Participant",
        );
        return apiRequest(ctx.app, {
          method: "POST",
          path: `/events/${eventId}/registrations`,
          token,
          payload: {},
          idempotencyKey: newIdempotencyKey(),
        });
      }),
    );

    const bodies = responses.map((response) => {
      assert.equal(response.statusCode, 200, response.body);
      return parseJson<{ state: string }>(response.body);
    });

    const registered = bodies.filter((row) => row.state === "Registered").length;
    const waitlisted = bodies.filter((row) => row.state === "Waitlisted").length;

    assert.equal(registered, capacity);
    assert.equal(waitlisted, attempts - capacity);

    const listResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/registrations?state=Registered&page=1&pageSize=100`,
      token: organizerToken,
    });
    assertOk(listResponse.statusCode, listResponse.body, "list registrations");
    const list = parseJson<PaginatedEnvelope<{ state: string }>>(listResponse.body);
    assert.equal(list.total, capacity);
  });

  it("AC-07: checked-in participant is marked Attended after event completion", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const participantSub = randomUUID();
    const participantToken = await signDevToken(ctx.app, participantSub, "Participant");
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

    const listResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/registrations?state=Attended&page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(listResponse.statusCode, listResponse.body, "attended registrations");
    const list = parseJson<
      PaginatedEnvelope<{ registrationId: string; state: string }>
    >(listResponse.body);
    const attended = list.items.find(
      (row) => row.registrationId === registered.registrationId,
    );
    assert.ok(attended, "expected attended registration in organizer list");
    assert.equal(attended.state, "Attended");
  });

  it("AC-10 / FR-21 / BR-18 / BR-19: organizer can list certificate-eligible participants with reasons", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
      feedbackRequired: true,
    });
    const participantSub = randomUUID();
    const participantToken = await signDevToken(ctx.app, participantSub, "Participant");
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

    await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/feedback`,
      token: participantToken,
      payload: { answers: { q1: 4 } },
    });

    const listResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/eligibility?page=1&pageSize=20`,
      token: organizerToken,
    });
    assertOk(listResponse.statusCode, listResponse.body, "eligibility list");
    const list = parseJson<
      PaginatedEnvelope<{
        registrationId: string;
        eligibility: { result: string; reasonCode: string; reasonText: string };
      }>
    >(listResponse.body);

    const entry = list.items.find(
      (row) => row.registrationId === registered.registrationId,
    );
    assert.ok(entry);
    assert.equal(entry.eligibility.result, "Eligible");
    assert.ok(entry.eligibility.reasonCode);
    assert.ok(entry.eligibility.reasonText);
  });

  it("AC-13: paginated list endpoints return correct envelope and empty page beyond totalPages", async () => {
    const prefix = `E2E Paginate ${randomUUID()}`;
    const createdIds: string[] = [];

    for (let index = 0; index < 4; index += 1) {
      const windows = defaultTimeWindows();
      const response = await apiRequest(ctx.app, {
        method: "POST",
        path: "/events",
        token: organizerToken,
        payload: {
          organizationId: "00000000-0000-0000-0000-000000000001",
          name: `${prefix} ${index}`,
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
      assertOk(response.statusCode, response.body, "seed event");
      createdIds.push(parseJson<{ eventId: string }>(response.body).eventId);
    }
    void createdIds;

    const page1Response = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?q=${encodeURIComponent(prefix)}&page=1&pageSize=2&sort=startAt:asc`,
      token: organizerToken,
    });
    assertOk(page1Response.statusCode, page1Response.body, "events page 1");
    const page1 = parseJson<PaginatedEnvelope<{ eventId: string }>>(page1Response.body);
    assert.equal(page1.page, 1);
    assert.equal(page1.pageSize, 2);
    assert.equal(page1.total, 4);
    assert.equal(page1.totalPages, 2);
    assert.equal(page1.items.length, 2);

    const beyondResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?q=${encodeURIComponent(prefix)}&page=99&pageSize=2`,
      token: organizerToken,
    });
    assertOk(beyondResponse.statusCode, beyondResponse.body, "events beyond last page");
    const beyond = parseJson<PaginatedEnvelope<unknown>>(beyondResponse.body);
    assert.deepEqual(beyond.items, []);
    assert.equal(beyond.total, 4);
    assert.equal(beyond.page, 99);
  });
});
