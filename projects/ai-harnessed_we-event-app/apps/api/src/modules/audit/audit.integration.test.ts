import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { closeDb, initDb } from "../../db/pool.js";
import { ensureAuditSchema } from "./repository.js";
import { auditService } from "./service.js";
import {
  createEvent,
  ensureEventSchema,
  transitionEventState,
  updateEvent,
} from "../event/repository.js";
import type { EventWithConfig } from "../event/types.js";
import { ensureIdempotencySchema } from "../../idempotency/index.js";
import {
  ensureRegistrationSchema,
} from "../registration/repository.js";
import { registrationService } from "../registration/service.js";
import {
  ensureTestOrganizerAdmin,
  ensureTestParticipant,
} from "../../test-helpers/participant-user.js";

const ACTOR_ID = "00000000-0000-0000-0000-000000000099";
const ORG_ID = "00000000-0000-0000-0000-000000000001";

function defaultWindows() {
  const now = Date.now();
  return {
    open: new Date(now - 3_600_000).toISOString(),
    close: new Date(now + 86_400_000).toISOString(),
  };
}

async function createRegistrationOpenEvent(options: {
  capacity: number;
}): Promise<EventWithConfig> {
  const windows = defaultWindows();
  const draft = await createEvent(
    {
      name: `Audit Test Event ${randomUUID()}`,
      startAt: windows.open,
      endAt: windows.close,
      ruleConfig: {
        capacity: options.capacity,
        waitlistEnabled: false,
        registrationOpenAt: windows.open,
        registrationCloseAt: windows.close,
        checkinOpenAt: windows.open,
        checkinCloseAt: windows.close,
        feedbackOpenAt: windows.open,
        feedbackCloseAt: windows.close,
      },
    },
    ACTOR_ID,
    "OrganizerAdmin",
    ORG_ID,
  );

  const transitionContext = {
    actorId: ACTOR_ID,
    actorRole: "OrganizerAdmin",
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
    throw new Error("Failed to open registration for test event");
  }
  return open;
}

describe("audit integration", () => {
  before(async () => {
    const databaseUrl =
      process.env.DATABASE_URL ??
      "postgresql://we_event:we_event@localhost:5432/we_event";
    await initDb(databaseUrl);
    await ensureEventSchema();
    await ensureAuditSchema();
    await ensureRegistrationSchema();
    await ensureIdempotencySchema();
    await ensureTestOrganizerAdmin(ACTOR_ID);
  });

  after(async () => {
    await closeDb();
  });

  it("AC-11 / TC-AC-11-001 / TC-AC-11-002: critical rule config changes are audit logged with actor and reason", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 10 });

    await updateEvent(
      event.id,
      {
        ruleConfig: { capacity: 20 },
        reasonCode: "CAPACITY_CHANGE",
        reasonText: "Expanded seats due to venue update",
      },
      ACTOR_ID,
      "OrganizerAdmin",
    );

    const { items } = await auditService.listAuditLogs(event.id, {
      entityType: "EventRuleConfig",
    });

    const ruleChange = items.find(
      (entry) => entry.action === "event.rule_config.updated",
    );
    assert.ok(ruleChange, "expected rule config audit entry");
    assert.equal(ruleChange.actorId, ACTOR_ID);
    assert.equal(ruleChange.actorRole, "OrganizerAdmin");
    assert.equal(ruleChange.reasonCode, "CAPACITY_CHANGE");
    assert.equal(ruleChange.reasonText, "Expanded seats due to venue update");
    assert.equal(ruleChange.before.capacity, 10);
    assert.equal(ruleChange.after.capacity, 20);
    assert.ok(ruleChange.occurredAt);
    assert.equal(ruleChange.entityType, "EventRuleConfig");
    assert.equal(ruleChange.eventId, event.id);
    assert.ok(ruleChange.entityId);
    assert.equal(ruleChange.action, "event.rule_config.updated");
  });

  it("AC-11 / TC-AC-11-006: non-capacity rule config field change is audit logged with before/after diff", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 10 });

    await updateEvent(
      event.id,
      {
        ruleConfig: { waitlistEnabled: true },
        reasonCode: "WAITLIST_ENABLED",
        reasonText: "Enable waitlist after venue confirmation",
      },
      ACTOR_ID,
      "OrganizerAdmin",
    );

    const { items } = await auditService.listAuditLogs(event.id, {
      entityType: "EventRuleConfig",
    });

    const waitlistChange = items.find(
      (entry) =>
        entry.action === "event.rule_config.updated" &&
        entry.reasonCode === "WAITLIST_ENABLED",
    );
    assert.ok(waitlistChange, "expected waitlist rule config audit entry");
    assert.equal(waitlistChange.before.waitlistEnabled, false);
    assert.equal(waitlistChange.after.waitlistEnabled, true);
    assert.equal(waitlistChange.actorId, ACTOR_ID);
    assert.equal(waitlistChange.reasonText, "Enable waitlist after venue confirmation");
  });

  it("AC-12 / TC-AC-12-001 / TC-AC-12-002: registration status changes are traceable via status history", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 5 });
    const participantId = randomUUID();
    await ensureTestParticipant(participantId);

    const registration = await registrationService.register(
      event.id,
      participantId,
      { actorId: participantId, actorRole: "Participant" },
    );

    await registrationService.cancel(
      event.id,
      registration.registrationId,
      { actorId: participantId, actorRole: "Participant" },
    );

    const { items } = await auditService.listStatusHistory(event.id, {
      registrationId: registration.registrationId,
      pageSize: "100",
      sort: "createdAt:asc",
    });

    assert.ok(items.length >= 2, "expected at least register and cancel entries");

    const accepted = items.find(
      (entry) => entry.action === "registration.accepted",
    );
    assert.ok(accepted, "expected registration.accepted entry");
    assert.equal(accepted.registrationId, registration.registrationId);
    assert.equal(accepted.afterState, "Registered");

    const cancelled = items.find(
      (entry) => entry.action === "registration.cancelled",
    );
    assert.ok(cancelled, "expected registration.cancelled entry");
    assert.equal(cancelled.registrationId, registration.registrationId);
    assert.equal(cancelled.afterState, "CancelledByUser");
    assert.ok(cancelled.occurredAt);
    assert.equal(accepted.actorId, participantId);
    assert.equal(accepted.actorRole, "Participant");
  });

  it("AC-12 / TC-AC-12-007: registrationId filter returns only that registration's transitions", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 10 });
    const participantA = randomUUID();
    const participantB = randomUUID();
    await ensureTestParticipant(participantA);
    await ensureTestParticipant(participantB);

    const regA = await registrationService.register(event.id, participantA, {
      actorId: participantA,
      actorRole: "Participant",
    });
    await registrationService.register(event.id, participantB, {
      actorId: participantB,
      actorRole: "Participant",
    });

    const { items } = await auditService.listStatusHistory(event.id, {
      registrationId: regA.registrationId,
      pageSize: "100",
    });

    assert.ok(items.length >= 1);
    for (const entry of items) {
      assert.equal(entry.registrationId, regA.registrationId);
    }
  });

  it("AC-12 / TC-AC-12-015: registrationId with no history returns empty paginated result", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 5 });
    const unusedRegistrationId = randomUUID();

    const result = await auditService.listStatusHistory(event.id, {
      registrationId: unusedRegistrationId,
    });

    assert.deepEqual(result.items, []);
    assert.equal(result.total, 0);
    assert.equal(result.page, 1);
    assert.equal(result.pageSize, 20);
  });

  it("AC-11 / TC-AC-11-017: audit logs default to newest-first when sort is omitted", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 10 });

    await updateEvent(
      event.id,
      {
        ruleConfig: { capacity: 15 },
        reasonCode: "CAPACITY_CHANGE",
        reasonText: "First expansion",
      },
      ACTOR_ID,
      "OrganizerAdmin",
    );

    await updateEvent(
      event.id,
      {
        ruleConfig: { capacity: 20 },
        reasonCode: "CAPACITY_CHANGE",
        reasonText: "Second expansion",
      },
      ACTOR_ID,
      "OrganizerAdmin",
    );

    const { items } = await auditService.listAuditLogs(event.id, {
      entityType: "EventRuleConfig",
    });

    const ruleChanges = items.filter(
      (entry) => entry.action === "event.rule_config.updated",
    );
    assert.ok(ruleChanges.length >= 2, "expected two rule config audit entries");

    for (let i = 1; i < ruleChanges.length; i++) {
      assert.ok(
        ruleChanges[i - 1]!.occurredAt >= ruleChanges[i]!.occurredAt,
        "expected descending occurredAt order",
      );
    }
  });

  it("AC-13 / TC-AC-13-004 / TC-AC-11-012 / TC-AC-12-014: paginated audit-logs and status-history return envelope metadata", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 3 });
    const participantIds = [randomUUID(), randomUUID(), randomUUID()];

    for (const participantId of participantIds) {
      await ensureTestParticipant(participantId);
      await registrationService.register(event.id, participantId, {
        actorId: participantId,
        actorRole: "Participant",
      });
    }

    const auditPage = await auditService.listAuditLogs(event.id, {
      page: "1",
      pageSize: "2",
    });
    assert.equal(auditPage.page, 1);
    assert.equal(auditPage.pageSize, 2);
    assert.ok(auditPage.total >= 3);
    assert.equal(auditPage.items.length, 2);
    assert.equal(auditPage.totalPages, Math.ceil(auditPage.total / 2));

    const beyondPage = await auditService.listAuditLogs(event.id, {
      page: String(auditPage.totalPages + 5),
      pageSize: "2",
    });
    assert.deepEqual(beyondPage.items, []);
    assert.equal(beyondPage.page, auditPage.totalPages + 5);
    assert.equal(beyondPage.total, auditPage.total);

    const historyPage = await auditService.listStatusHistory(event.id, {
      page: "1",
      pageSize: "2",
      sort: "createdAt:asc",
    });
    assert.equal(historyPage.page, 1);
    assert.equal(historyPage.pageSize, 2);
    assert.ok(historyPage.total >= 3);
    assert.equal(historyPage.items.length, 2);
    assert.equal(historyPage.totalPages, Math.ceil(historyPage.total / 2));

    const page2 = await auditService.listAuditLogs(event.id, {
      page: "2",
      pageSize: "2",
    });
    assert.equal(page2.total, auditPage.total);
    assert.equal(page2.totalPages, auditPage.totalPages);
  });
});
