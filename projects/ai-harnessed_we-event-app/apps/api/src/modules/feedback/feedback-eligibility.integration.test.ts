import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { closeDb, initDb } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { ensureIdempotencySchema } from "../../idempotency/index.js";
import { checkinService } from "../checkin/service.js";
import { ensureCheckinSchema } from "../checkin/repository.js";
import {
  createEvent,
  findEventById,
  transitionEventState,
} from "../event/repository.js";
import { ensureEventSchema } from "../event/repository.js";
import { eventService } from "../event/service.js";
import type { EventWithConfig } from "../event/types.js";
import {
  createRegistration,
  ensureRegistrationSchema,
} from "../registration/repository.js";
import { registrationService } from "../registration/service.js";
import { ensureEligibilitySchema } from "../eligibility/repository.js";
import { eligibilityService } from "../eligibility/service.js";
import { ensureFeedbackSchema } from "../feedback/repository.js";
import { feedbackService } from "../feedback/service.js";

const ORG_ADMIN_ID = "00000000-0000-0000-0000-000000000099";
const ORG_ID = "00000000-0000-0000-0000-000000000001";

function eventWindows() {
  const now = Date.now();
  return {
    open: new Date(now - 3_600_000).toISOString(),
    close: new Date(now + 86_400_000).toISOString(),
  };
}

async function createCompletedEventWithAttendee(options?: {
  feedbackRequired?: boolean;
}): Promise<{
  event: EventWithConfig;
  participantId: string;
  registrationId: string;
}> {
  const windows = eventWindows();
  const participantId = randomUUID();

  const draft = await createEvent(
    {
      name: `Feedback Test ${randomUUID()}`,
      startAt: windows.open,
      endAt: windows.close,
      ruleConfig: {
        capacity: 10,
        waitlistEnabled: false,
        registrationOpenAt: windows.open,
        registrationCloseAt: windows.close,
        checkinOpenAt: windows.open,
        checkinCloseAt: windows.close,
        feedbackRequired: options?.feedbackRequired ?? true,
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
    action: "test.transition",
  };

  await transitionEventState(draft.id, "Published", {
    ...ctx,
    action: "event.published",
  });
  await transitionEventState(draft.id, "RegistrationOpen", {
    ...ctx,
    action: "event.registration_opened",
  });

  const registered = await registrationService.register(
    draft.id,
    participantId,
    { actorId: participantId, actorRole: "Participant" },
  );

  await transitionEventState(draft.id, "RegistrationClosed", {
    ...ctx,
    action: "event.registration_closed",
  });
  await transitionEventState(draft.id, "InProgress", {
    ...ctx,
    action: "event.started",
  });

  await checkinService.staffCheckin(
    draft.id,
    { registrationId: registered.registrationId },
    { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
  );

  const completed = await eventService.complete(draft.id, {
    actorId: ORG_ADMIN_ID,
    actorRole: "OrganizerAdmin",
  });

  const event = await findEventById(completed.eventId);
  if (!event) {
    throw new Error("Failed to load completed event");
  }

  return {
    event,
    participantId,
    registrationId: registered.registrationId,
  };
}

describe("feedback and eligibility integration", () => {
  before(async () => {
    const databaseUrl =
      process.env.DATABASE_URL ??
      "postgresql://we_event:we_event@localhost:5432/we_event";
    await initDb(databaseUrl);
    await ensureEventSchema();
    await ensureRegistrationSchema();
    await ensureCheckinSchema();
    await ensureFeedbackSchema();
    await ensureEligibilitySchema();
    await ensureIdempotencySchema();
  });

  after(async () => {
    await closeDb();
  });

  it("AC-08: participant can submit feedback within feedback window", async () => {
    const { event, participantId } = await createCompletedEventWithAttendee();

    const result = await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 5, q2: "Great session" } },
      { actorId: participantId, actorRole: "Participant" },
    );

    assert.ok(result.feedbackId);
    assert.equal(result.participantId, participantId);
    assert.ok(result.submittedAt);
    assert.deepEqual(result.answers, { q1: 5, q2: "Great session" });
  });

  it("rejects feedback outside the feedback window", async () => {
    const windows = eventWindows();
    const participantId = randomUUID();

    const draft = await createEvent(
      {
        name: `Closed Feedback ${randomUUID()}`,
        startAt: windows.open,
        endAt: windows.close,
        ruleConfig: {
          capacity: 5,
          registrationOpenAt: windows.open,
          registrationCloseAt: windows.close,
          checkinOpenAt: windows.open,
          checkinCloseAt: windows.close,
          feedbackOpenAt: new Date(Date.now() + 86_400_000).toISOString(),
          feedbackCloseAt: new Date(Date.now() + 172_800_000).toISOString(),
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

    await checkinService.staffCheckin(
      draft.id,
      { registrationId: registered.id },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    await eventService.complete(draft.id, {
      actorId: ORG_ADMIN_ID,
      actorRole: "OrganizerAdmin",
    });

    await assert.rejects(
      () =>
        feedbackService.submit(
          draft.id,
          participantId,
          { answers: { q1: 3 } },
          { actorId: participantId, actorRole: "Participant" },
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.FEEDBACK_NOT_ALLOWED);
        return true;
      },
    );
  });

  it("AC-09: eligibility evaluation returns Eligible with reason after feedback", async () => {
    const { event, participantId } = await createCompletedEventWithAttendee();

    await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 4 } },
      { actorId: participantId, actorRole: "Participant" },
    );

    const result = await eligibilityService.getMyEligibility(
      event.id,
      participantId,
      { actorId: participantId, actorRole: "Participant" },
    );

    assert.equal(result.result, "Eligible");
    assert.ok(result.reasonCode);
    assert.ok(result.reasonText);
    assert.ok(result.evaluatedAt);
  });

  it("AC-09: eligibility is NotEligible when mandatory feedback is missing", async () => {
    const { event, participantId } = await createCompletedEventWithAttendee({
      feedbackRequired: true,
    });

    const result = await eligibilityService.getMyEligibility(
      event.id,
      participantId,
      { actorId: participantId, actorRole: "Participant" },
    );

    assert.equal(result.result, "NotEligible");
    assert.equal(
      result.reasonCode,
      VALIDATION_ERROR_CODES.NOT_ELIGIBLE_FEEDBACK,
    );
  });

  it("AC-10: organizer can list eligibility with reasons", async () => {
    const { event, participantId, registrationId } =
      await createCompletedEventWithAttendee();

    await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 5 } },
      { actorId: participantId, actorRole: "Participant" },
    );

    const list = await eligibilityService.listEligibility(
      event.id,
      { page: "1", pageSize: "20" },
      {
        actorId: ORG_ADMIN_ID,
        actorRole: "OrganizerAdmin",
      },
    );

    const entry = list.items.find(
      (item) => item.registrationId === registrationId,
    );
    assert.ok(entry);
    assert.equal(entry.eligibility.result, "Eligible");
    assert.ok(entry.eligibility.reasonCode);
    assert.ok(entry.eligibility.reasonText);
  });

  it("admin can revoke eligible participant with reason", async () => {
    const { event, participantId, registrationId } =
      await createCompletedEventWithAttendee();

    await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 5 } },
      { actorId: participantId, actorRole: "Participant" },
    );

    await eligibilityService.getMyEligibility(event.id, participantId, {
      actorId: participantId,
      actorRole: "Participant",
    });

    const revoked = await eligibilityService.revoke(
      event.id,
      registrationId,
      {
        reasonCode: "ADMIN_REVOKED",
        reasonText: "Certificate policy violation.",
      },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    assert.equal(revoked.result, "Revoked");
    assert.equal(revoked.reasonCode, "ADMIN_REVOKED");
    assert.equal(revoked.overriddenBy, ORG_ADMIN_ID);
  });

  it("AC-13: paginated eligibility list returns envelope metadata", async () => {
    const { event, participantId } = await createCompletedEventWithAttendee();

    await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 5 } },
      { actorId: participantId, actorRole: "Participant" },
    );

    const page = await eligibilityService.listEligibility(
      event.id,
      { page: "1", pageSize: "1" },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    assert.equal(page.page, 1);
    assert.equal(page.pageSize, 1);
    assert.ok(page.total >= 1);
    assert.ok(page.totalPages >= 1);
    assert.equal(page.items.length, 1);

    const beyond = await eligibilityService.listEligibility(
      event.id,
      { page: "99", pageSize: "1" },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );
    assert.deepEqual(beyond.items, []);
    assert.equal(beyond.total, page.total);
  });
});
