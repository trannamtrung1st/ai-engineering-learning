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
  ensureTestOrganizerAdmin,
  ensureTestParticipant,
} from "../../test-helpers/participant-user.js";
import {
  countSeatHolders,
  createRegistration,
  ensureRegistrationSchema,
  findRegistrationById,
} from "./repository.js";
import { registrationService } from "./service.js";
import { checkinService } from "../checkin/service.js";
import { eventService } from "../event/service.js";

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

async function newParticipantId(): Promise<string> {
  const participantId = randomUUID();
  await ensureTestParticipant(participantId);
  return participantId;
}

describe("registration integration (NFR-02, FR-31)", () => {
  before(async () => {
    const databaseUrl =
      process.env.DATABASE_URL ??
      "postgresql://we_event:we_event@localhost:5432/we_event";
    await initDb(databaseUrl);
    await ensureEventSchema();
    await ensureRegistrationSchema();
    await ensureIdempotencySchema();
    await ensureTestOrganizerAdmin(ACTOR_ID);
  });

  after(async () => {
    await closeDb();
  });

  it("AC-01 / BR-02: assigns Registered when seats are available", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 5 });
    const participantId = await newParticipantId();

    const result = await registrationService.register(
      event.id,
      participantId,
      actorContext,
    );

    assert.equal(result.state, "Registered");
    assert.equal(result.waitlistPosition, null);
  });

  it("AC-02 / FR-09: rejects registration when full and waitlist disabled (BR-05)", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: false,
    });

    const first = await newParticipantId();
    const second = await newParticipantId();

    await registrationService.register(event.id, first, actorContext);

    await assert.rejects(
      () => registrationService.register(event.id, second, actorContext),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(
          error.code,
          VALIDATION_ERROR_CODES.REGISTRATION_REJECTED_FULL,
        );
        assert.equal(error.statusCode, 422);
        return true;
      },
    );
  });

  it("AC-02: assigns Waitlisted when full and waitlist enabled", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });

    const first = await newParticipantId();
    const second = await newParticipantId();

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
    const participantId = await newParticipantId();

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
    const participantIds = await Promise.all(
      Array.from({ length: attempts }, () => newParticipantId()),
    );
    const results = await Promise.allSettled(
      participantIds.map((participantId) =>
        createRegistration(event.id, participantId, actorContext),
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

  it("FR-12 / BR-06 / BR-08 / NFR-02: promotes waitlisted participant FIFO when a seat is released atomically", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 1,
      waitlistEnabled: true,
    });

    const firstParticipant = await newParticipantId();
    const secondParticipant = await newParticipantId();
    const thirdParticipant = await newParticipantId();

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

  it("AC-13 / FR-31 / NFR-16: paginated registrations and waitlist lists", async () => {
    const event = await createRegistrationOpenEvent({
      capacity: 2,
      waitlistEnabled: true,
    });

    const registeredIds: string[] = [];
    for (let index = 0; index < 2; index += 1) {
      const result = await registrationService.register(
        event.id,
        await newParticipantId(),
        actorContext,
      );
      registeredIds.push(result.registrationId);
    }

    for (let index = 0; index < 3; index += 1) {
      await registrationService.register(
        event.id,
        await newParticipantId(),
        actorContext,
      );
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

  it("FR-10 / BR-02: registration-status returns null when participant is not registered", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 5 });
    const participantId = await newParticipantId();

    const status = await registrationService.getStatus(event.id, participantId);

    assert.equal(status.registration, null);
  });

  it("FR-10: registration-status works for default dev participant sub", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 5 });
    await ensureTestParticipant("participant-1");

    const status = await registrationService.getStatus(event.id, "participant-1");

    assert.equal(status.registration, null);
  });

  it("FR-10 / NFR-09: registration-status returns active registration after register", async () => {
    const event = await createRegistrationOpenEvent({ capacity: 5 });
    const participantId = await newParticipantId();
    const participantContext = {
      actorId: participantId,
      actorRole: "Participant" as const,
    };

    const registered = await registrationService.register(
      event.id,
      participantId,
      participantContext,
    );

    const status = await registrationService.getStatus(event.id, participantId);

    assert.ok(status.registration);
    assert.equal(status.registration.registrationId, registered.registrationId);
    assert.equal(status.registration.state, "Registered");
    assert.equal(status.registration.eventId, event.id);
    assert.equal(status.registration.participantId, participantId);
  });

  it("AC-08 / FR-19 / BR-15: registration-status returns Attended after event completion", async () => {
    const windows = defaultWindows();
    const participantId = await newParticipantId();
    const participantContext = {
      actorId: participantId,
      actorRole: "Participant" as const,
    };

    const draft = await createEvent(
      {
        name: `Feedback Status ${randomUUID()}`,
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
      ACTOR_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    await transitionEventState(draft.id, "Published", {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
      action: "test",
    });
    await transitionEventState(draft.id, "RegistrationOpen", {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
      action: "test",
    });

    const registered = await registrationService.register(
      draft.id,
      participantId,
      participantContext,
    );

    await transitionEventState(draft.id, "InProgress", {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
      action: "test",
    });

    await checkinService.staffCheckin(
      draft.id,
      { registrationId: registered.registrationId },
      { actorId: ACTOR_ID, actorRole: "OrganizerAdmin" },
    );

    await eventService.complete(draft.id, {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    });

    const row = await findRegistrationById(registered.registrationId);
    assert.equal(row?.state, "Attended");

    const status = await registrationService.getStatus(draft.id, participantId);
    assert.ok(status.registration);
    assert.equal(status.registration.state, "Attended");
  });

  it("AC-13: GET /me/registrations returns paginated participant registrations", async () => {
    const participantId = await newParticipantId();
    const participantContext = {
      actorId: participantId,
      actorRole: "Participant" as const,
    };

    const eventA = await createRegistrationOpenEvent({ capacity: 5 });
    const eventB = await createRegistrationOpenEvent({ capacity: 5 });

    const regA = await registrationService.register(
      eventA.id,
      participantId,
      participantContext,
    );
    const regB = await registrationService.register(
      eventB.id,
      participantId,
      participantContext,
    );

    const page = await registrationService.listMyRegistrations(participantId, {
      page: "1",
      pageSize: "1",
    });

    assert.equal(page.page, 1);
    assert.equal(page.pageSize, 1);
    assert.equal(page.total, 2);
    assert.equal(page.totalPages, 2);
    assert.equal(page.items.length, 1);
    assert.ok(page.items[0]?.eventName);
    assert.ok(
      [regA.registrationId, regB.registrationId].includes(
        page.items[0]!.registrationId,
      ),
    );

    const beyond = await registrationService.listMyRegistrations(participantId, {
      page: "99",
      pageSize: "1",
    });
    assert.deepEqual(beyond.items, []);
    assert.equal(beyond.total, 2);
  });

  it("FR-29 / FR-31 / NFR-16: my registrations includes gating context and waitlist details", async () => {
    const participantId = await newParticipantId();
    const participantContext = {
      actorId: participantId,
      actorRole: "Participant" as const,
    };

    const event = await createRegistrationOpenEvent({ capacity: 5 });
    await registrationService.register(event.id, participantId, participantContext);

    const page = await registrationService.listMyRegistrations(participantId, {
      page: "1",
      pageSize: "20",
    });

    const item = page.items.find((row) => row.eventId === event.id);
    assert.ok(item);
    assert.equal(item.state, "Registered");
    assert.equal(item.eventState, "RegistrationOpen");
    assert.ok(item.checkinOpenAt);
    assert.ok(item.checkinCloseAt);
    assert.ok(item.feedbackOpenAt);
    assert.ok(item.feedbackCloseAt);
    assert.equal(item.waitlistPosition, null);
    assert.equal(item.reasonText, null);
  });
});
