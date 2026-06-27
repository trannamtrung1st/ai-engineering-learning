import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import {
  createRegistrationOpenEvent,
  registerParticipant,
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
 * Flow C (testing plan §6): admin critical rule change after registration open →
 * audit verification.
 */
describe("Flow C — governance and traceability (AC-11, AC-12)", () => {
  let ctx: E2EContext;
  let organizerToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("AC-11: critical rule config change is audit logged with actor and reason", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 10,
    });

    const patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: organizerToken,
      payload: {
        ruleConfig: { capacity: 25 },
        reasonCode: "CAPACITY_CHANGE",
        reasonText: "Venue expansion for e2e scenario",
      },
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(patchResponse.statusCode, patchResponse.body, "patch capacity");

    const auditResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/audit-logs?entityType=EventRuleConfig`,
      token: organizerToken,
    });
    assertOk(auditResponse.statusCode, auditResponse.body, "audit logs");
    const audit = parseJson<
      PaginatedEnvelope<{
        action: string;
        actorId: string;
        reasonCode: string;
        reasonText: string;
        before: { capacity: number };
        after: { capacity: number };
        occurredAt: string;
      }>
    >(auditResponse.body);

    const ruleChange = audit.items.find(
      (entry) => entry.action === "event.rule_config.updated",
    );
    assert.ok(ruleChange, "expected rule config audit entry");
    assert.equal(ruleChange.reasonCode, "CAPACITY_CHANGE");
    assert.equal(ruleChange.reasonText, "Venue expansion for e2e scenario");
    assert.equal(ruleChange.before.capacity, 10);
    assert.equal(ruleChange.after.capacity, 25);
    assert.ok(ruleChange.occurredAt);
    assert.ok(ruleChange.actorId);
  });

  it("AC-12: registration status history traces state transitions", async () => {
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const participantSub = randomUUID();
    const participantToken = await signDevToken(ctx.app, participantSub, "Participant");

    const registered = await registerParticipant(ctx.app, participantToken, eventId);

    const cancelResponse = await apiRequest(ctx.app, {
      method: "POST",
      path: `/events/${eventId}/registrations/${registered.registrationId}/cancel`,
      token: participantToken,
      payload: {},
      idempotencyKey: newIdempotencyKey(),
    });
    assertOk(cancelResponse.statusCode, cancelResponse.body, "cancel registration");

    const historyResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}/status-history?registrationId=${registered.registrationId}&sort=createdAt:asc`,
      token: organizerToken,
    });
    assertOk(historyResponse.statusCode, historyResponse.body, "status history");
    const history = parseJson<
      PaginatedEnvelope<{
        action: string;
        registrationId: string;
        afterState: string;
        occurredAt: string;
      }>
    >(historyResponse.body);

    assert.ok(history.items.length >= 2);

    const accepted = history.items.find(
      (entry) => entry.action === "registration.accepted",
    );
    assert.ok(accepted);
    assert.equal(accepted.registrationId, registered.registrationId);
    assert.equal(accepted.afterState, "Registered");

    const cancelled = history.items.find(
      (entry) => entry.action === "registration.cancelled",
    );
    assert.ok(cancelled);
    assert.equal(cancelled.afterState, "CancelledByUser");
    assert.ok(cancelled.occurredAt);
  });
});
