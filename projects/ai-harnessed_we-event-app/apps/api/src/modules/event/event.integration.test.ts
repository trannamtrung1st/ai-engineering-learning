import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { closeDb, initDb } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { ensureIdempotencySchema } from "../../idempotency/index.js";
import { auditService } from "../audit/service.js";
import { ensureAuditSchema } from "../audit/repository.js";
import {
  ensureTestOrganizerAdmin,
  ensureTestParticipant,
} from "../../test-helpers/participant-user.js";
import { ensureRegistrationSchema, registrationService } from "../registration/index.js";
import {
  createEvent,
  ensureEventSchema,
  findEventById,
  listEvents,
} from "./repository.js";
import { eventService } from "./service.js";
import type { CreateEventInput } from "./types.js";
import { assertPublishReady, resolveTransition } from "./validation.js";

const ACTOR_ID = "00000000-0000-0000-0000-000000000099";
const ORG_ID = "00000000-0000-0000-0000-000000000001";

function defaultWindows() {
  const now = Date.now();
  return {
    open: new Date(now + 86_400_000).toISOString(),
    close: new Date(now + 172_800_000).toISOString(),
    regOpen: new Date(now).toISOString(),
    regClose: new Date(now + 86_400_000).toISOString(),
  };
}

function createInput(overrides: Partial<CreateEventInput> = {}): CreateEventInput {
  const windows = defaultWindows();
  return {
    name: `Event ${randomUUID()}`,
    description: "Integration test event",
    location: "Room A",
    startAt: windows.open,
    endAt: windows.close,
    ruleConfig: {
      capacity: 10,
      waitlistEnabled: false,
      registrationOpenAt: windows.regOpen,
      registrationCloseAt: windows.regClose,
      checkinOpenAt: windows.regOpen,
      checkinCloseAt: windows.regClose,
      feedbackOpenAt: windows.regOpen,
      feedbackCloseAt: windows.regClose,
    },
    ...overrides,
  };
}

describe("event integration", () => {
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

  it("creates a draft event with rule config", async () => {
    const input = createInput({ name: "Draft Workshop" });
    const created = await eventService.create(input, ACTOR_ID, "OrganizerAdmin");

    assert.equal(created.state, "Draft");
    assert.equal(created.name, "Draft Workshop");
    assert.equal(created.ruleConfig.capacity, 10);

    const loaded = await findEventById(created.eventId);
    assert.ok(loaded);
    assert.equal(loaded.state, "Draft");
  });

  it("AC-13: paginated list returns items, total, and totalPages", async () => {
    const prefix = `Paginate ${randomUUID()}`;
    for (let index = 0; index < 3; index += 1) {
      await createEvent(
        createInput({ name: `${prefix} ${index}` }),
        ACTOR_ID,
        "OrganizerAdmin",
        ORG_ID,
      );
    }

    const page1 = await eventService.list("OrganizerAdmin", {
      q: prefix,
      page: "1",
      pageSize: "2",
      sort: "startAt:asc",
    });

    assert.equal(page1.page, 1);
    assert.equal(page1.pageSize, 2);
    assert.ok(page1.total >= 3);
    assert.equal(page1.totalPages, Math.ceil(page1.total / 2));
    assert.equal(page1.items.length, 2);

    const beyond = await eventService.list("OrganizerAdmin", {
      q: prefix,
      page: String(page1.totalPages + 5),
      pageSize: "2",
    });

    assert.deepEqual(beyond.items, []);
    assert.equal(beyond.total, page1.total);
    assert.equal(beyond.totalPages, page1.totalPages);
  });

  it("filters participant-visible states only", async () => {
    const draft = await createEvent(
      createInput({ name: `Hidden ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const participantList = await eventService.list("Participant", {
      q: draft.name,
    });
    assert.equal(participantList.items.length, 0);

    const adminList = await eventService.list("OrganizerAdmin", {
      q: draft.name,
    });
    assert.equal(adminList.items.length, 1);
    assert.equal(adminList.items[0]?.state, "Draft");
  });

  it("publishes when required fields are complete", async () => {
    const draft = await createEvent(
      createInput({ name: `Publish ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const published = await eventService.publish(draft.id, {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    });

    assert.equal(published.state, "Published");
  });

  it("rejects publish when location is missing", async () => {
    const draft = await createEvent(
      {
        ...createInput(),
        location: "",
      },
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    assert.throws(
      () => assertPublishReady(draft),
      (error: unknown) => error instanceof ApiError && error.statusCode === 422,
    );
  });

  it("pauses registration while open", async () => {
    const draft = await createEvent(
      createInput({ name: `Pause ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    await eventService.publish(draft.id, {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    });
    const open = await eventService.openRegistration(draft.id, {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    });
    assert.equal(open.state, "RegistrationOpen");

    const paused = await eventService.pause(draft.id, {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
      reasonText: "Capacity review",
    });
    assert.equal(paused.state, "RegistrationOpen");
    assert.equal(paused.ruleConfig.registrationPaused, true);
  });

  it("runs lifecycle transitions through completion", async () => {
    const draft = await createEvent(
      createInput({ name: `Lifecycle ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const context = {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    };

    await eventService.publish(draft.id, context);
    await eventService.openRegistration(draft.id, context);
    await eventService.closeRegistration(draft.id, context);
    await eventService.start(draft.id, context);
    const completed = await eventService.complete(draft.id, context);

    assert.equal(completed.state, "Completed");
  });

  it("rejects illegal state transitions", async () => {
    const draft = await createEvent(
      createInput({ name: `Illegal ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    assert.throws(
      () => resolveTransition(draft.state, "startEvent"),
      (error: unknown) =>
        error instanceof ApiError && error.code === "INVALID_STATE_TRANSITION",
    );
  });

  it("NFR-14 / FR-03: updates draft event rule config including registration window", async () => {
    const draft = await createEvent(
      createInput({ name: `RuleConfig ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );
    const windows = defaultWindows();
    const laterOpen = new Date(Date.parse(windows.regOpen) + 3_600_000).toISOString();
    const laterClose = new Date(Date.parse(windows.regClose) + 3_600_000).toISOString();

    const updated = await eventService.update(
      draft.id,
      {
        ruleConfig: {
          capacity: 25,
          waitlistEnabled: true,
          registrationOpenAt: laterOpen,
          registrationCloseAt: laterClose,
        },
      },
      {
        actorId: ACTOR_ID,
        actorRole: "OrganizerAdmin",
      },
    );

    assert.equal(updated.ruleConfig.capacity, 25);
    assert.equal(updated.ruleConfig.waitlistEnabled, true);
    assert.equal(updated.ruleConfig.registrationOpenAt, laterOpen);
  });

  it("NFR-14 / FR-02 / FR-03 / TC-NFR-14-004: rule config version increments on successive updates", async () => {
    const draft = await createEvent(
      createInput({ name: `Versioned ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );
    const context = {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    };

    const first = await eventService.update(
      draft.id,
      { ruleConfig: { capacity: 20 } },
      context,
    );
    const second = await eventService.update(
      draft.id,
      {
        ruleConfig: {
          registrationOpenAt: new Date(
            Date.parse(first.ruleConfig.registrationOpenAt) + 1_800_000,
          ).toISOString(),
        },
      },
      context,
    );

    assert.equal(first.ruleConfig.version, 2);
    assert.equal(second.ruleConfig.version, 3);
  });

  it("NFR-14 / TC-NFR-14-007: rule config updates persist in Postgres via service layer", async () => {
    const draft = await createEvent(
      createInput({ name: `Persisted ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    await eventService.update(
      draft.id,
      { ruleConfig: { capacity: 42 } },
      {
        actorId: ACTOR_ID,
        actorRole: "OrganizerAdmin",
      },
    );

    const loaded = await findEventById(draft.id);
    assert.ok(loaded);
    assert.equal(loaded.ruleConfig.capacity, 42);
    assert.ok(loaded.ruleConfig.version >= 2);
  });

  it("BR-03 / NFR-14 / FR-02 / TC-NFR-14-013: capacity reduction below Registered count is rejected", async () => {
    const capacity = 20;
    const registeredTarget = 15;
    const baseInput = createInput({ name: `CapacityGuard ${randomUUID()}` });
    const draft = await createEvent(
      {
        ...baseInput,
        ruleConfig: {
          ...baseInput.ruleConfig,
          capacity,
          waitlistEnabled: false,
        },
      },
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const context = {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    };

    await eventService.publish(draft.id, context);
    await eventService.openRegistration(draft.id, context);

    for (let index = 0; index < registeredTarget; index += 1) {
      const participantId = randomUUID();
      await ensureTestParticipant(participantId);
      await registrationService.register(draft.id, participantId, {
        actorId: participantId,
        actorRole: "Participant",
      });
    }

    await assert.rejects(
      () =>
        eventService.update(
          draft.id,
          {
            ruleConfig: { capacity: 10 },
            reasonCode: "CAPACITY_DECREASE",
            reasonText: "Attempt to reduce below registered count",
          },
          context,
        ),
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === VALIDATION_ERROR_CODES.CAPACITY_EXCEEDED &&
        error.statusCode === 422,
    );

    const loaded = await findEventById(draft.id);
    assert.ok(loaded);
    assert.equal(loaded.ruleConfig.capacity, capacity);
  });

  it("AC-11 / BR-22 / TC-AC-11-014: sequential critical config changes produce distinct immutable audit entries", async () => {
    const draft = await createEvent(
      createInput({ name: `SequentialAudit ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const context = {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    };

    await eventService.publish(draft.id, context);
    await eventService.openRegistration(draft.id, context);

    await eventService.update(
      draft.id,
      {
        ruleConfig: { capacity: 15 },
        reasonCode: "CAPACITY_INCREASE",
        reasonText: "First expansion for early demand",
      },
      context,
    );

    await eventService.update(
      draft.id,
      {
        ruleConfig: { capacity: 20 },
        reasonCode: "CAPACITY_INCREASE",
        reasonText: "Second expansion after waitlist interest",
      },
      context,
    );

    const { items } = await auditService.listAuditLogs(draft.id, {
      entityType: "EventRuleConfig",
      pageSize: "100",
      sort: "createdAt:asc",
    });
    const ruleConfigEntries = items.filter(
      (entry) => entry.action === "event.rule_config.updated",
    );

    assert.ok(
      ruleConfigEntries.length >= 2,
      "expected at least two rule config audit entries",
    );

    const [first, second] = ruleConfigEntries.slice(-2);
    assert.ok(first && second, "expected two sequential audit entries");

    assert.equal(first.before.capacity, 10);
    assert.equal(first.after.capacity, 15);
    assert.equal(first.reasonText, "First expansion for early demand");

    assert.equal(second.before.capacity, 15);
    assert.equal(second.after.capacity, 20);
    assert.equal(second.reasonText, "Second expansion after waitlist interest");

    assert.ok(
      Date.parse(second.occurredAt) >= Date.parse(first.occurredAt),
      "expected monotonic occurredAt ordering",
    );
  });

  it("AC-11 / NFR-10 / BR-22 / TC-AC-11-015: every successful post-open critical config change has exactly one audit record", async () => {
    const draft = await createEvent(
      createInput({ name: `Audit ${randomUUID()}` }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const context = {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    };

    await eventService.publish(draft.id, context);
    await eventService.openRegistration(draft.id, context);

    await assert.rejects(
      () =>
        eventService.update(
          draft.id,
          { ruleConfig: { capacity: 20 } },
          context,
        ),
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === VALIDATION_ERROR_CODES.AUDIT_REQUIRED_FOR_CRITICAL_CHANGE,
    );

    const beforeAudit = await auditService.listAuditLogs(draft.id, {
      entityType: "EventRuleConfig",
      pageSize: "100",
    });
    const ruleConfigAuditCountBefore = beforeAudit.items.filter(
      (entry) => entry.action === "event.rule_config.updated",
    ).length;

    await eventService.update(
      draft.id,
      {
        ruleConfig: { capacity: 20 },
        reasonCode: "CAPACITY_INCREASE",
        reasonText: "Higher demand than forecast",
      },
      context,
    );

    const afterAudit = await auditService.listAuditLogs(draft.id, {
      entityType: "EventRuleConfig",
      pageSize: "100",
    });
    const ruleConfigEntries = afterAudit.items.filter(
      (entry) => entry.action === "event.rule_config.updated",
    );

    assert.equal(
      ruleConfigEntries.length,
      ruleConfigAuditCountBefore + 1,
      "expected exactly one new audit record for the critical config change",
    );

    const latest = ruleConfigEntries[0];
    assert.ok(latest, "expected rule config audit entry");
    assert.equal(latest.action, "event.rule_config.updated");
    assert.equal(latest.actorId, ACTOR_ID);
    assert.equal(latest.actorRole, "OrganizerAdmin");
    assert.equal(latest.reasonCode, "CAPACITY_INCREASE");
    assert.equal(latest.reasonText, "Higher demand than forecast");
    assert.ok(latest.occurredAt);
  });

  it("repository list supports search and sort", async () => {
    const marker = randomUUID();
    await createEvent(
      createInput({
        name: `Alpha ${marker}`,
        location: "North Hall",
      }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );
    await createEvent(
      createInput({
        name: `Beta ${marker}`,
        location: "South Hall",
      }),
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const result = await listEvents({
      q: marker,
      sortColumn: "e.name",
      sortDirection: "ASC",
      limit: 10,
      offset: 0,
    });

    assert.ok(result.total >= 2);
    assert.equal(result.items[0]?.name.startsWith("Alpha"), true);
  });
});
