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
});
