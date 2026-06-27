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
import {
  ensureEligibilitySchema,
  findEligibilityByRegistrationId,
} from "../eligibility/repository.js";
import { eligibilityService } from "../eligibility/service.js";
import { ensureFeedbackSchema } from "../feedback/repository.js";
import { feedbackService } from "../feedback/service.js";
import {
  ensureTestOrganizerAdmin,
  ensureTestParticipant,
} from "../../test-helpers/participant-user.js";

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
  participantId?: string;
}): Promise<{
  event: EventWithConfig;
  participantId: string;
  registrationId: string;
}> {
  const windows = eventWindows();
  const participantId = options?.participantId ?? randomUUID();
  await ensureTestParticipant(participantId);

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

async function createCompletedEventWithTwoAttendees(options?: {
  feedbackRequired?: boolean;
}): Promise<{
  event: EventWithConfig;
  participantA: { id: string; registrationId: string };
  participantB: { id: string; registrationId: string };
}> {
  const windows = eventWindows();
  const participantAId = randomUUID();
  const participantBId = randomUUID();
  await ensureTestParticipant(participantAId);
  await ensureTestParticipant(participantBId);

  const draft = await createEvent(
    {
      name: `Multi Eligibility ${randomUUID()}`,
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

  const registeredA = await registrationService.register(
    draft.id,
    participantAId,
    { actorId: participantAId, actorRole: "Participant" },
  );
  const registeredB = await registrationService.register(
    draft.id,
    participantBId,
    { actorId: participantBId, actorRole: "Participant" },
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
    { registrationId: registeredA.registrationId },
    { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
  );
  await checkinService.staffCheckin(
    draft.id,
    { registrationId: registeredB.registrationId },
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
    participantA: {
      id: participantAId,
      registrationId: registeredA.registrationId,
    },
    participantB: {
      id: participantBId,
      registrationId: registeredB.registrationId,
    },
  };
}

describe("feedback and eligibility integration (FR-19, FR-21, BR-15, BR-16, BR-18, BR-19, BR-20)", () => {
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
    await ensureTestOrganizerAdmin(ORG_ADMIN_ID);
  });

  after(async () => {
    await closeDb();
  });

  it("AC-08 / FR-19 / BR-15: participant can submit feedback within feedback window", async () => {
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

  it("TC-AC-08-022 / AC-08: dev sub alias submits feedback with registrationId without false ownership error", async () => {
    const devSub = "participant-1";
    const { event, registrationId } = await createCompletedEventWithAttendee({
      participantId: devSub,
    });

    const result = await feedbackService.submit(
      event.id,
      devSub,
      { registrationId, answers: { q1: 5, q2: "Great session" } },
      { actorId: devSub, actorRole: "Participant" },
    );

    assert.ok(result.feedbackId);
    assert.ok(result.submittedAt);
    assert.deepEqual(result.answers, { q1: 5, q2: "Great session" });
  });

  it("rejects feedback outside the feedback window (BR-15)", async () => {
    const windows = eventWindows();
    const participantId = randomUUID();
    await ensureTestParticipant(participantId);

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

  it("allows feedback update within the feedback window (BR-16 allows in-window edits)", async () => {
    const { event, participantId } = await createCompletedEventWithAttendee();

    const first = await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 4 } },
      { actorId: participantId, actorRole: "Participant" },
    );

    const updated = await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 5 } },
      { actorId: participantId, actorRole: "Participant" },
    );

    assert.equal(updated.feedbackId, first.feedbackId);
    assert.deepEqual(updated.answers, { q1: 5 });
  });

  it("TC-AC-09-002 / AC-09 / FR-20 / BR-18 / BR-19: getMyEligibility persists Eligible result with reason in certificate_eligibilities", async () => {
    const { event, participantId, registrationId } =
      await createCompletedEventWithAttendee();

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

    const persisted = await findEligibilityByRegistrationId(registrationId);
    assert.ok(persisted);
    assert.equal(persisted.result, result.result);
    assert.equal(persisted.reasonCode, result.reasonCode);
    assert.equal(persisted.reasonText, result.reasonText);
    assert.ok(persisted.evaluatedAt);
  });

  it("TC-FR-26-007 / FR-20a / FR-26 / AC-09: getMyEligibility returns only current actor eligibility", async () => {
    const { event, participantA, participantB } =
      await createCompletedEventWithTwoAttendees();

    await feedbackService.submit(
      event.id,
      participantA.id,
      { answers: { q1: 5 } },
      { actorId: participantA.id, actorRole: "Participant" },
    );

    const myResult = await eligibilityService.getMyEligibility(
      event.id,
      participantA.id,
      { actorId: participantA.id, actorRole: "Participant" },
    );

    const organizerList = await eligibilityService.listEligibility(
      event.id,
      { page: "1", pageSize: "20" },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    const entryA = organizerList.items.find(
      (item) => item.registrationId === participantA.registrationId,
    );
    const entryB = organizerList.items.find(
      (item) => item.registrationId === participantB.registrationId,
    );
    assert.ok(entryA);
    assert.ok(entryB);
    assert.equal(entryA.participantId, participantA.id);
    assert.equal(entryA.eligibility.result, myResult.result);
    assert.equal(entryA.eligibility.reasonCode, myResult.reasonCode);
    assert.equal(entryA.eligibility.reasonText, myResult.reasonText);
    assert.equal(entryB.eligibility.result, "NotEligible");
    assert.notEqual(entryB.eligibility.result, myResult.result);
  });

  it("TC-FR-26-019 / FR-20a / FR-26 / AC-09: getMyEligibility scoped to actor identity only returns own eligibility", async () => {
    const { event, participantA, participantB } =
      await createCompletedEventWithTwoAttendees();

    await feedbackService.submit(
      event.id,
      participantA.id,
      { answers: { q1: 5 } },
      { actorId: participantA.id, actorRole: "Participant" },
    );

    const resultA = await eligibilityService.getMyEligibility(
      event.id,
      participantA.id,
      { actorId: participantA.id, actorRole: "Participant" },
    );
    const resultB = await eligibilityService.getMyEligibility(
      event.id,
      participantB.id,
      { actorId: participantB.id, actorRole: "Participant" },
    );

    assert.equal(resultA.result, "Eligible");
    assert.equal(resultB.result, "NotEligible");
    assert.notEqual(resultA.reasonCode, resultB.reasonCode);
  });

  it("AC-09 / BR-18 / BR-19: eligibility evaluation returns Eligible with reason after feedback", async () => {
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

  it("TC-AC-09-012 / BR-19: eligibility refreshes to Eligible after feedback submission", async () => {
    const { event, participantId } = await createCompletedEventWithAttendee({
      feedbackRequired: true,
    });

    const before = await eligibilityService.getMyEligibility(
      event.id,
      participantId,
      { actorId: participantId, actorRole: "Participant" },
    );
    assert.equal(before.result, "NotEligible");

    await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 5 } },
      { actorId: participantId, actorRole: "Participant" },
    );

    const after = await eligibilityService.getMyEligibility(
      event.id,
      participantId,
      { actorId: participantId, actorRole: "Participant" },
    );
    assert.equal(after.result, "Eligible");
    assert.ok(after.reasonCode);
    assert.ok(after.reasonText);
    assert.ok(after.evaluatedAt);
  });

  it("TC-AC-09-016 / BR-18 / BR-19: eligibility evaluation is deterministic for identical inputs", async () => {
    const { event, participantId } = await createCompletedEventWithAttendee();

    await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 4 } },
      { actorId: participantId, actorRole: "Participant" },
    );

    const first = await eligibilityService.getMyEligibility(
      event.id,
      participantId,
      { actorId: participantId, actorRole: "Participant" },
    );
    const second = await eligibilityService.getMyEligibility(
      event.id,
      participantId,
      { actorId: participantId, actorRole: "Participant" },
    );

    assert.equal(first.result, second.result);
    assert.equal(first.reasonCode, second.reasonCode);
    assert.equal(first.reasonText, second.reasonText);
  });

  it("AC-09 / BR-18 / BR-19: eligibility is NotEligible when mandatory feedback is missing", async () => {
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

  it("TC-AC-10-005 / FR-21 / BR-18 / BR-19: organizer list shows NotEligible when feedback missing", async () => {
    const { event, participantId, registrationId } =
      await createCompletedEventWithAttendee({ feedbackRequired: true });

    const list = await eligibilityService.listEligibility(
      event.id,
      { page: "1", pageSize: "20" },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    const entry = list.items.find(
      (item) => item.registrationId === registrationId,
    );
    assert.ok(entry);
    assert.equal(entry.participantId, participantId);
    assert.equal(entry.eligibility.result, "NotEligible");
    assert.equal(
      entry.eligibility.reasonCode,
      VALIDATION_ERROR_CODES.NOT_ELIGIBLE_FEEDBACK,
    );
    assert.ok(entry.eligibility.reasonText);
  });

  it("AC-10 / FR-21 / BR-18 / BR-19: organizer can list eligibility with reasons", async () => {
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

  it("TC-AC-10-008 / FR-21 / FR-37 / BR-20: revoked eligibility appears in organizer list", async () => {
    const { event, participantId, registrationId } =
      await createCompletedEventWithAttendee();

    await feedbackService.submit(
      event.id,
      participantId,
      { answers: { q1: 5 } },
      { actorId: participantId, actorRole: "Participant" },
    );

    await eligibilityService.revoke(
      event.id,
      registrationId,
      {
        reasonCode: "ADMIN_REVOKED",
        reasonText: "Certificate policy violation.",
      },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    const list = await eligibilityService.listEligibility(
      event.id,
      { page: "1", pageSize: "20", eligibility: "Revoked" },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );

    const entry = list.items.find(
      (item) => item.registrationId === registrationId,
    );
    assert.ok(entry);
    assert.equal(entry.eligibility.result, "Revoked");
    assert.equal(entry.eligibility.reasonCode, "ADMIN_REVOKED");
    assert.equal(entry.eligibility.reasonText, "Certificate policy violation.");
    assert.equal(entry.eligibility.overriddenBy, ORG_ADMIN_ID);
  });

  it("FR-21 / BR-20: admin can revoke eligible participant with reason", async () => {
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
