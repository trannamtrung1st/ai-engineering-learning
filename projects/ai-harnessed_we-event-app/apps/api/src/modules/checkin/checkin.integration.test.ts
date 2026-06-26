import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { closeDb, initDb } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { ensureIdempotencySchema } from "../../idempotency/index.js";
import {
  createEvent,
  transitionEventState,
} from "../event/repository.js";
import { ensureEventSchema } from "../event/repository.js";
import { eventService } from "../event/service.js";
import type { EventWithConfig } from "../event/types.js";
import {
  createRegistration,
  ensureRegistrationSchema,
  findRegistrationById,
} from "../registration/repository.js";
import { registrationService } from "../registration/service.js";
import { ensureCheckinSchema } from "./repository.js";
import { checkinService } from "./service.js";
import {
  ensureTestOrganizerAdmin,
  ensureTestParticipant,
} from "../../test-helpers/participant-user.js";

const ORG_ADMIN_ID = "00000000-0000-0000-0000-000000000099";
const ORG_ID = "00000000-0000-0000-0000-000000000001";

function checkinWindows() {
  const now = Date.now();
  return {
    open: new Date(now - 3_600_000).toISOString(),
    close: new Date(now + 86_400_000).toISOString(),
  };
}

async function createCheckinableEvent(): Promise<{
  event: EventWithConfig;
  participantId: string;
  registrationId: string;
}> {
  const windows = checkinWindows();
  const participantId = randomUUID();
  await ensureTestParticipant(participantId);

  const draft = await createEvent(
    {
      name: `Checkin Test ${randomUUID()}`,
      startAt: windows.open,
      endAt: windows.close,
      ruleConfig: {
        capacity: 10,
        waitlistEnabled: false,
        registrationOpenAt: windows.open,
        registrationCloseAt: windows.close,
        checkinOpenAt: windows.open,
        checkinCloseAt: windows.close,
        feedbackOpenAt: windows.open,
        feedbackCloseAt: windows.close,
      },
    },
    ORG_ADMIN_ID,
    "OrganizerAdmin",
    ORG_ID,
  );

  const transitionContext = {
    actorId: ORG_ADMIN_ID,
    actorRole: "OrganizerAdmin" as const,
    action: "test.transition",
  };

  await transitionEventState(draft.id, "Published", {
    ...transitionContext,
    action: "event.published",
  });
  await transitionEventState(draft.id, "RegistrationOpen", {
    ...transitionContext,
    action: "event.registration_opened",
  });

  const registered = await registrationService.register(
    draft.id,
    participantId,
    { actorId: participantId, actorRole: "Participant" },
  );

  await transitionEventState(draft.id, "RegistrationClosed", {
    ...transitionContext,
    action: "event.registration_closed",
  });
  const inProgress = await transitionEventState(draft.id, "InProgress", {
    ...transitionContext,
    action: "event.started",
  });

  if (!inProgress) {
    throw new Error("Failed to start test event");
  }

  return {
    event: inProgress,
    participantId,
    registrationId: registered.registrationId,
  };
}

describe("checkin integration (NFR-02, BR-13)", () => {
  before(async () => {
    const databaseUrl =
      process.env.DATABASE_URL ??
      "postgresql://we_event:we_event@localhost:5432/we_event";
    await initDb(databaseUrl);
    await ensureEventSchema();
    await ensureRegistrationSchema();
    await ensureCheckinSchema();
    await ensureIdempotencySchema();
    await ensureTestOrganizerAdmin(ORG_ADMIN_ID);
  });

  after(async () => {
    await closeDb();
  });

  it("AC-05 / FR-13 / FR-15: in-window check-in is recorded with timestamp", async () => {
    const { event, participantId, registrationId } =
      await createCheckinableEvent();

    const result = await checkinService.staffCheckin(
      event.id,
      { registrationId },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    assert.equal(result.registrationState, "CheckedIn");
    assert.equal(result.participantId, participantId);
    assert.ok(result.checkinAt);
    assert.equal(result.method, "Staff");
  });

  it("AC-06 / FR-14 / FR-16: out-of-window check-in is rejected", async () => {
    const windows = checkinWindows();
    const participantId = randomUUID();
    await ensureTestParticipant(participantId);

    const draft = await createEvent(
      {
        name: `Closed Window ${randomUUID()}`,
        startAt: windows.open,
        endAt: windows.close,
        ruleConfig: {
          capacity: 5,
          registrationOpenAt: windows.open,
          registrationCloseAt: windows.close,
          checkinOpenAt: new Date(Date.now() + 86_400_000).toISOString(),
          checkinCloseAt: new Date(Date.now() + 172_800_000).toISOString(),
          feedbackOpenAt: windows.open,
          feedbackCloseAt: windows.close,
        },
      },
      ORG_ADMIN_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const ctx = {
      actorId: ORG_ADMIN_ID,
      actorRole: "OrganizerAdmin" as const,
      action: "test",
    };

    await transitionEventState(draft.id, "Published", {
      ...ctx,
      action: "event.published",
    });
    await transitionEventState(draft.id, "RegistrationOpen", {
      ...ctx,
      action: "event.registration_opened",
    });

    const registered = await createRegistration(draft.id, participantId, {
      actorId: participantId,
      actorRole: "Participant",
    });

    await transitionEventState(draft.id, "InProgress", {
      ...ctx,
      action: "event.started",
    });

    await assert.rejects(
      () =>
        checkinService.staffCheckin(
          draft.id,
          { registrationId: registered.id },
          { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED);
        return true;
      },
    );
  });

  it("rejects duplicate check-in for same registration", async () => {
    const { event, registrationId } = await createCheckinableEvent();
    const context = { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" as const };

    await checkinService.staffCheckin(event.id, { registrationId }, context);

    await assert.rejects(
      () =>
        checkinService.staffCheckin(event.id, { registrationId }, context),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(
          error.code,
          VALIDATION_ERROR_CODES.CHECKIN_ALREADY_RECORDED,
        );
        return true;
      },
    );
  });

  it("AC-07: checked-in participant is marked Attended after event completion", async () => {
    const { event, registrationId } = await createCheckinableEvent();

    await checkinService.staffCheckin(
      event.id,
      { registrationId },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    await eventService.complete(event.id, {
      actorId: ORG_ADMIN_ID,
      actorRole: "OrganizerAdmin",
    });

    const registration = await findRegistrationById(registrationId);
    assert.equal(registration?.state, "Attended");
  });

  it("marks Registered participants without check-in as Absent on completion", async () => {
    const windows = checkinWindows();
    const noShowId = randomUUID();
    const checkedInId = randomUUID();
    await ensureTestParticipant(noShowId);
    await ensureTestParticipant(checkedInId);

    const draft = await createEvent(
      {
        name: `Attendance Mix ${randomUUID()}`,
        startAt: windows.open,
        endAt: windows.close,
        ruleConfig: {
          capacity: 10,
          registrationOpenAt: windows.open,
          registrationCloseAt: windows.close,
          checkinOpenAt: windows.open,
          checkinCloseAt: windows.close,
          feedbackOpenAt: windows.open,
          feedbackCloseAt: windows.close,
        },
      },
      ORG_ADMIN_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const ctx = {
      actorId: ORG_ADMIN_ID,
      actorRole: "OrganizerAdmin" as const,
      action: "test",
    };

    await transitionEventState(draft.id, "Published", {
      ...ctx,
      action: "event.published",
    });
    await transitionEventState(draft.id, "RegistrationOpen", {
      ...ctx,
      action: "event.registration_opened",
    });

    const noShow = await createRegistration(draft.id, noShowId, {
      actorId: noShowId,
      actorRole: "Participant",
    });
    const checkedIn = await createRegistration(draft.id, checkedInId, {
      actorId: checkedInId,
      actorRole: "Participant",
    });

    await transitionEventState(draft.id, "InProgress", {
      ...ctx,
      action: "event.started",
    });

    await checkinService.staffCheckin(
      draft.id,
      { registrationId: checkedIn.id },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    await eventService.complete(draft.id, {
      actorId: ORG_ADMIN_ID,
      actorRole: "OrganizerAdmin",
    });

    const noShowAfter = await findRegistrationById(noShow.id);
    const checkedInAfter = await findRegistrationById(checkedIn.id);

    assert.equal(noShowAfter?.state, "Absent");
    assert.equal(checkedInAfter?.state, "Attended");
  });

  it("participant self check-in succeeds during InProgress (FR-13, BR-13)", async () => {
    const { event, participantId, registrationId } =
      await createCheckinableEvent();

    const result = await checkinService.selfCheckin(event.id, participantId, {
      actorId: participantId,
      actorRole: "Participant",
    });

    assert.equal(result.registrationId, registrationId);
    assert.equal(result.method, "Self");
    assert.equal(result.operatorId, null);
  });

  it("AC-13: paginated attendance list returns envelope metadata", async () => {
    const windows = checkinWindows();
    const ctx = {
      actorId: ORG_ADMIN_ID,
      actorRole: "OrganizerAdmin" as const,
      action: "test",
    };

    const draft = await createEvent(
      {
        name: `Attendance Pagination ${randomUUID()}`,
        startAt: windows.open,
        endAt: windows.close,
        ruleConfig: {
          capacity: 20,
          registrationOpenAt: windows.open,
          registrationCloseAt: windows.close,
          checkinOpenAt: windows.open,
          checkinCloseAt: windows.close,
          feedbackOpenAt: windows.open,
          feedbackCloseAt: windows.close,
        },
      },
      ORG_ADMIN_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    await transitionEventState(draft.id, "Published", {
      ...ctx,
      action: "event.published",
    });
    await transitionEventState(draft.id, "RegistrationOpen", {
      ...ctx,
      action: "event.registration_opened",
    });

    const registrationIds: string[] = [];
    for (let index = 0; index < 5; index += 1) {
      const participantId = randomUUID();
      await ensureTestParticipant(participantId);
      const row = await createRegistration(draft.id, participantId, {
        actorId: participantId,
        actorRole: "Participant",
      });
      registrationIds.push(row.id);
    }

    await transitionEventState(draft.id, "InProgress", {
      ...ctx,
      action: "event.started",
    });

    const staffContext = {
      actorId: ORG_ADMIN_ID,
      actorRole: "OrganizerAdmin" as const,
    };

    await checkinService.staffCheckin(
      draft.id,
      { registrationId: registrationIds[0]! },
      staffContext,
    );
    await checkinService.staffCheckin(
      draft.id,
      { registrationId: registrationIds[1]! },
      staffContext,
    );

    const page = await checkinService.listAttendance(draft.id, {
      page: "1",
      pageSize: "3",
    });

    assert.equal(page.page, 1);
    assert.equal(page.pageSize, 3);
    assert.equal(page.total, 5);
    assert.equal(page.totalPages, 2);
    assert.equal(page.items.length, 3);

    const beyond = await checkinService.listAttendance(draft.id, {
      page: "99",
      pageSize: "3",
    });
    assert.deepEqual(beyond.items, []);
    assert.equal(beyond.total, 5);
    assert.equal(beyond.totalPages, 2);

    const sorted = await checkinService.listAttendance(draft.id, {
      page: "1",
      pageSize: "5",
      sort: "checkinAt:desc",
    });
    assert.equal(sorted.items.filter((item) => item.checkinAt !== null).length, 2);
    assert.ok(sorted.items[0]?.checkinAt);
    assert.ok(sorted.items[1]?.checkinAt);
  });
});
