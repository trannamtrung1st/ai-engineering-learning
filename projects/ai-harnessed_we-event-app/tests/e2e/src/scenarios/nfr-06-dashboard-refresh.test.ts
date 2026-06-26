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

interface DashboardSummary {
  eventId: string;
  registrations: number;
  registeredSeats: number;
  waitlist: number;
  checkedIn: number;
  capacity: number;
}

async function fetchDashboard(
  ctx: E2EContext,
  token: string,
  eventId: string,
): Promise<DashboardSummary> {
  const response = await apiRequest(ctx.app, {
    method: "GET",
    path: `/events/${eventId}/dashboard`,
    token,
  });
  assertOk(response.statusCode, response.body, "FR-22 dashboard");
  return parseJson<DashboardSummary>(response.body);
}

/**
 * NFR-06 near-real-time organizer visibility — dashboard reads reflect latest
 * authoritative backend totals within one refresh window (FR-22).
 */
describe("NFR-06 / FR-22 dashboard refresh (e2e)", () => {
  let ctx: E2EContext;
  let organizerToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("TC-NFR-06-004: registration KPI increments after new registration", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken, {
      capacity: 20,
    });

    await transitionEvent(ctx.app, organizerToken, eventId, "publish");
    await transitionEvent(ctx.app, organizerToken, eventId, "open-registration");

    const baseline = await fetchDashboard(ctx, organizerToken, eventId);
    assert.equal(baseline.registrations, 0);

    const participantToken = await signDevToken(
      ctx.app,
      randomUUID(),
      "Participant",
    );

    const registerResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/registrations`,
      token: participantToken,
      payload: {},
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(registerResponse.statusCode, registerResponse.body, "register");

    const updated = await fetchDashboard(ctx, organizerToken, eventId);
    assert.equal(updated.registrations, baseline.registrations + 1);
    assert.equal(updated.registeredSeats, baseline.registeredSeats + 1);
  });

  it("TC-NFR-06-013: concurrent registrations yield consistent dashboard total", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken, {
      capacity: 50,
    });

    await transitionEvent(ctx.app, organizerToken, eventId, "publish");
    await transitionEvent(ctx.app, organizerToken, eventId, "open-registration");

    const baseline = await fetchDashboard(ctx, organizerToken, eventId);
    const participantCount = 5;

    await Promise.all(
      Array.from({ length: participantCount }, async () => {
        const participantToken = await signDevToken(
          ctx.app,
          randomUUID(),
          "Participant",
        );
        const response = await apiRequest(ctx.app, {
          method: "POST",
          path: `/events/${eventId}/registrations`,
          token: participantToken,
          payload: {},
          idempotencyKey: newIdempotencyKey(),
        });
        assertOk(response.statusCode, response.body, "parallel register");
      }),
    );

    const updated = await fetchDashboard(ctx, organizerToken, eventId);
    assert.equal(updated.registrations, baseline.registrations + participantCount);
    assert.equal(updated.registeredSeats, baseline.registeredSeats + participantCount);
  });
});
