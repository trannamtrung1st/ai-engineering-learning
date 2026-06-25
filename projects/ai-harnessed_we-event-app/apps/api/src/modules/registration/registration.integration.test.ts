import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { closeDb, getPool, initDb } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { ensureEventSchema } from "../event/repository.js";
import {
  createEvent,
  transitionEventState,
} from "../event/repository.js";
import type { EventWithConfig } from "../event/types.js";
import { ensureIdempotencySchema } from "../../idempotency/index.js";
import {
  countSeatHolders,
  createRegistration,
  ensureRegistrationSchema,
} from "./repository.js";
import { registrationService } from "./service.js";

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
  waitlistEnabled?: boolean;
}): Promise<EventWithConfig> {
  const windows = defaultWindows();
  const draft = await createEvent(
    {
      name: `Test Event ${randomUUID()}`,
      startAt: windows.open,
      endAt: windows.close,
      ruleConfig: {
        capacity: options.capacity,
        waitlistEnabled: options.waitlistEnabled ?? false,
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
    action: "test.transition",
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

const actorContext = { actorId: ACTOR_ID, actorRole: "Participant" };

describe("registration integration", () => {
  before(async () => {
    const databaseUrl =
      process.env.DATABASE_URL ??
      "postgresql://we_event:we_event@localhost:5432/we_event";
    await initDb(databaseUrl);
    await ensureEventSchema();
    await ensureRegistrationSchema();
    await ensureIdempotencySchema();
  });

  after(async () => {
    await closeDb();
  });

  it("AC-01: assigns Registered when seats are available", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 5 });
    const participantId = randomUUID();

    const result = await registrationService.register(
      event.id,
      participantId,
      actorContext,
    );

    assert.equal(result.state, "Registered");
    assert.equal(result.waitlistPosition, null);
  });

  it("AC-02: assigns Waitlisted when full and waitlist enabled", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });

    const first = randomUUID();
    const second = randomUUID();

    const registered = await registrationService.register(
      event.id,
      first,
      actorContext,
    );
    assert.equal(registered.state, "Registered");

    const waitlisted = await registrationService.register(
      event.id,
      second,
      actorContext,
    );
    assert.equal(waitlisted.state, "Waitlisted");
    assert.equal(waitlisted.waitlistPosition, 1);
  });

  it("AC-03: blocks duplicate registration for same participant and event", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 10 });
    const participantId = randomUUID();

    await registrationService.register(event.id, participantId, actorContext);

    await assert.rejects(
      () => registrationService.register(event.id, participantId, actorContext),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(
          error.code,
          VALIDATION_ERROR_CODES.REGISTRATION_DUPLICATE_ACTIVE,
        );
        assert.equal(error.statusCode, 409);
        return true;
      },
    );
  });

  it("AC-04: concurrent registrations never exceed capacity", async () => {
    const capacity = 3;
    const event = await createRegistrationOpenEvent({
      capacity,
      waitlistEnabled: true,
    });

    const attempts = 12;
    const results = await Promise.allSettled(
      Array.from({ length: attempts }, () =>
        createRegistration(event.id, randomUUID(), actorContext),
      ),
    );

    const fulfilled = results.filter((r) => r.status === "fulfilled");
    assert.equal(fulfilled.length, attempts);

    const registeredCount = await countSeatHolders(event.id, getPool());

    assert.ok(
      registeredCount <= capacity,
      `registered count ${registeredCount} exceeded capacity ${capacity}`,
    );
    assert.equal(registeredCount, capacity);

    const waitlisted = fulfilled.filter(
      (r) => r.value.state === "Waitlisted",
    ).length;
    assert.equal(waitlisted, attempts - capacity);
  });

  it("promotes waitlisted participant FIFO when a seat is released", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });

    const firstParticipant = randomUUID();
    const secondParticipant = randomUUID();
    const thirdParticipant = randomUUID();

    const first = await registrationService.register(
      event.id,
      firstParticipant,
      actorContext,
    );
    const second = await registrationService.register(
      event.id,
      secondParticipant,
      actorContext,
    );
    const third = await registrationService.register(
      event.id,
      thirdParticipant,
      actorContext,
    );

    assert.equal(first.state, "Registered");
    assert.equal(second.waitlistPosition, 1);
    assert.equal(third.waitlistPosition, 2);

    const cancelResult = await registrationService.cancel(
      event.id,
      first.registrationId,
      { actorId: firstParticipant, actorRole: "Participant" },
    );

    assert.equal(cancelResult.cancelled.state, "CancelledByUser");
    assert.ok(cancelResult.promoted);
    assert.equal(cancelResult.promoted.registrationId, second.registrationId);
    assert.equal(cancelResult.promoted.state, "Registered");

    const waitlist = await registrationService.listWaitlist(event.id, {
      page: "1",
      pageSize: "20",
    });
    assert.equal(waitlist.items.length, 1);
    assert.equal(waitlist.items[0]?.registrationId, third.registrationId);
    assert.equal(waitlist.items[0]?.position, 2);
  });

  it("AC-13: paginated registrations and waitlist lists", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 2,
      waitlistEnabled: true,
    });

    const registeredIds: string[] = [];
    for (let index = 0; index < 2; index += 1) {
      const result = await registrationService.register(
        event.id,
        randomUUID(),
        actorContext,
      );
      registeredIds.push(result.registrationId);
    }

    for (let index = 0; index < 3; index += 1) {
      await registrationService.register(event.id, randomUUID(), actorContext);
    }

    const registrationsPage = await registrationService.listRegistrations(
      event.id,
      { page: "1", pageSize: "3" },
    );

    assert.equal(registrationsPage.page, 1);
    assert.equal(registrationsPage.pageSize, 3);
    assert.equal(registrationsPage.total, 5);
    assert.equal(registrationsPage.totalPages, 2);
    assert.equal(registrationsPage.items.length, 3);

    const beyond = await registrationService.listRegistrations(event.id, {
      page: "99",
      pageSize: "3",
    });
    assert.deepEqual(beyond.items, []);
    assert.equal(beyond.total, 5);
    assert.equal(beyond.totalPages, 2);

    const waitlistPage = await registrationService.listWaitlist(event.id, {
      page: "1",
      pageSize: "2",
      sort: "position:asc",
    });

    assert.equal(waitlistPage.total, 3);
    assert.equal(waitlistPage.items.length, 2);
    assert.equal(waitlistPage.items[0]?.position, 1);
    assert.equal(waitlistPage.items[1]?.position, 2);

    const filtered = await registrationService.listRegistrations(event.id, {
      state: "Registered",
      page: "1",
      pageSize: "20",
    });
    assert.equal(filtered.total, 2);
    assert.ok(
      filtered.items.every((item) => item.state === "Registered"),
    );
  });
});
