import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { closeDb, initDb } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { auditService } from "../audit/service.js";
import { ensureAuditSchema } from "../audit/repository.js";
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

  it("AC-11: audits critical rule config changes after registration opens", async () => {
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

    await eventService.update(
      draft.id,
      {
        ruleConfig: { capacity: 20 },
        reasonCode: "CAPACITY_INCREASE",
        reasonText: "Higher demand than forecast",
      },
      context,
    );

    const { entries } = await auditService.listAuditLogs(draft.id, {
      entityType: "EventRuleConfig",
    });

    assert.ok(
      entries.some((entry) => entry.action === "event.rule_config.updated"),
    );
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
