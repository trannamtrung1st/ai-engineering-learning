import { randomUUID } from "node:crypto";

import { resolveActorId } from "../auth/resolve-actor-id.js";
import { getPool } from "../db/pool.js";
import { ensureIdempotencySchema } from "../idempotency/index.js";
import { CheckinService } from "../modules/checkin/service.js";
import { ensureCheckinSchema } from "../modules/checkin/repository.js";
import {
  createEvent,
  ensureEventSchema,
  findEventById,
  transitionEventState,
} from "../modules/event/repository.js";
import { EventService } from "../modules/event/service.js";
import {
  createRegistration,
  ensureRegistrationSchema,
} from "../modules/registration/repository.js";
import { RegistrationService } from "../modules/registration/service.js";
import {
  ensureUserSchema,
  provisionTestUser,
} from "../modules/user/repository.js";
import { TEST_PASSWORD_HASH } from "../modules/auth/password.js";
import {
  ensureTestOrganizerAdmin,
  ensureTestParticipant,
} from "../test-helpers/participant-user.js";

export const SEED_ORG_ID = "00000000-0000-0000-0000-000000000001";
export const SEED_ORG_ADMIN_ID = "00000000-0000-0000-0000-000000000099";
export const SEED_ORG_STAFF_ID = "00000000-0000-0000-0000-000000000098";
export const SEED_PARTICIPANT_SUB = "participant-1";
export const SEED_MARKER = "browser-fixture";

export interface DevSeedFixtures {
  bulkRegistrationsEventId: string;
  staffSub: string;
  staffAssignedEventIds: string[];
  participantSub: string;
  checkinEventId: string;
  waitlistEventId: string;
  feedbackEventId: string;
}

let cachedFixtures: DevSeedFixtures | null = null;

function seedWindows() {
  const now = Date.now();
  return {
    open: new Date(now - 3_600_000).toISOString(),
    close: new Date(now + 86_400_000 * 7).toISOString(),
  };
}

async function findEventIdByName(name: string): Promise<string | null> {
  const result = await getPool().query<{ id: string }>(
    "SELECT id FROM events WHERE name = $1 LIMIT 1",
    [name],
  );
  return result.rows[0]?.id ?? null;
}

async function countEventRegistrations(eventId: string): Promise<number> {
  const result = await getPool().query<{ count: string }>(
    "SELECT COUNT(*)::text AS count FROM registrations WHERE event_id = $1",
    [eventId],
  );
  return Number(result.rows[0]?.count ?? 0);
}

async function ensureBulkRegistrationsEvent(
  context: { actorId: string; actorRole: "OrganizerAdmin" },
): Promise<string> {
  const name = `SEED ${SEED_MARKER} registrations`;
  const existingId = await findEventIdByName(name);
  if (existingId) {
    const total = await countEventRegistrations(existingId);
    if (total >= 25) {
      return existingId;
    }
  }

  const windows = seedWindows();
  const eventService = new EventService();
  let eventId = existingId;

  if (!eventId) {
    const draft = await createEvent(
      {
        name,
        description: "Browser fixture — organizer registrations pagination",
        location: "Seed Hall",
        startAt: windows.open,
        endAt: windows.close,
        ruleConfig: {
          capacity: 100,
          waitlistEnabled: false,
          registrationOpenAt: windows.open,
          registrationCloseAt: windows.close,
          checkinOpenAt: windows.open,
          checkinCloseAt: windows.close,
          feedbackOpenAt: windows.open,
          feedbackCloseAt: windows.close,
        },
      },
      context.actorId,
      context.actorRole,
      SEED_ORG_ID,
    );
    eventId = draft.id;
    await eventService.publish(eventId, context);
    await eventService.openRegistration(eventId, context);
  }

  const current = await countEventRegistrations(eventId);
  const needed = Math.max(0, 25 - current);
  for (let index = 0; index < needed; index += 1) {
    const participantId = randomUUID();
    await ensureTestParticipant(participantId);
    await createRegistration(eventId, participantId, {
      actorId: participantId,
      actorRole: "Participant",
    });
  }

  return eventId;
}

async function ensureStaffAssignedEvents(
  context: { actorId: string; actorRole: "OrganizerAdmin" },
): Promise<string[]> {
  const eventService = new EventService();
  const windows = seedWindows();
  const assignedIds: string[] = [];

  for (let index = 1; index <= 25; index += 1) {
    const name = `SEED ${SEED_MARKER} staff-assign-${String(index).padStart(2, "0")}`;
    let eventId = await findEventIdByName(name);
    if (!eventId) {
      const draft = await createEvent(
        {
          name,
          description: "Browser fixture — staff assigned events pagination",
          location: "Staff Wing",
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
        context.actorId,
        context.actorRole,
        SEED_ORG_ID,
      );
      eventId = draft.id;
      await eventService.publish(eventId, context);
    }
    assignedIds.push(eventId);
  }

  await provisionTestUser(
    SEED_ORG_STAFF_ID,
    "OrganizerStaff",
    "Seed Organizer Staff",
    TEST_PASSWORD_HASH,
    {
      organizationId: SEED_ORG_ID,
      assignedEventIds: assignedIds,
    },
  );

  return assignedIds;
}

async function ensureCheckinFixture(
  participantId: string,
  context: { actorId: string; actorRole: "OrganizerAdmin" },
): Promise<string> {
  const name = `SEED ${SEED_MARKER} check-in`;
  const existingId = await findEventIdByName(name);
  if (existingId) {
    const event = await findEventById(existingId);
    if (event?.state === "InProgress") {
      return existingId;
    }
  }

  const windows = seedWindows();
  const eventService = new EventService();
  const registrationService = new RegistrationService();

  const draft = existingId
    ? (await findEventById(existingId))!
    : await createEvent(
        {
          name,
          description: "Browser fixture — participant check-in quick action",
          location: "Check-in Lobby",
          startAt: windows.open,
          endAt: windows.close,
          ruleConfig: {
            capacity: 20,
            waitlistEnabled: false,
            registrationOpenAt: windows.open,
            registrationCloseAt: windows.close,
            checkinOpenAt: windows.open,
            checkinCloseAt: windows.close,
            feedbackOpenAt: windows.open,
            feedbackCloseAt: windows.close,
            selfCheckinEnabled: true,
          },
        },
        context.actorId,
        context.actorRole,
        SEED_ORG_ID,
      );

  const eventId = draft.id;

  if (draft.state === "Draft") {
    await eventService.publish(eventId, context);
    await eventService.openRegistration(eventId, context);
  }

  const existingRegistration = await getPool().query(
    `SELECT id FROM registrations
     WHERE event_id = $1 AND participant_id = $2 AND state = 'Registered'
     LIMIT 1`,
    [eventId, participantId],
  );

  if (existingRegistration.rows.length === 0) {
    await registrationService.register(eventId, participantId, {
      actorId: participantId,
      actorRole: "Participant",
    });
  }

  const refreshed = await findEventById(eventId);
  if (refreshed?.state === "RegistrationOpen") {
    await eventService.closeRegistration(eventId, context);
  }
  const afterClose = await findEventById(eventId);
  if (afterClose?.state !== "InProgress") {
    await transitionEventState(eventId, "InProgress", {
      ...context,
      action: "event.started",
    });
  }

  return eventId;
}

async function ensureWaitlistFixture(
  participantId: string,
  context: { actorId: string; actorRole: "OrganizerAdmin" },
): Promise<string> {
  const name = `SEED ${SEED_MARKER} waitlist`;
  const existingId = await findEventIdByName(name);
  if (existingId) {
    const waitlisted = await getPool().query(
      `SELECT id FROM registrations
       WHERE event_id = $1 AND participant_id = $2 AND state = 'Waitlisted'
       LIMIT 1`,
      [existingId, participantId],
    );
    if (waitlisted.rows.length > 0) {
      return existingId;
    }
  }

  const windows = seedWindows();
  const eventService = new EventService();
  const registrationService = new RegistrationService();

  const draft = existingId
    ? (await findEventById(existingId))!
    : await createEvent(
        {
          name,
          description: "Browser fixture — waitlist position display",
          location: "Queue Room",
          startAt: windows.open,
          endAt: windows.close,
          ruleConfig: {
            capacity: 1,
            waitlistEnabled: true,
            registrationOpenAt: windows.open,
            registrationCloseAt: windows.close,
            checkinOpenAt: windows.open,
            checkinCloseAt: windows.close,
            feedbackOpenAt: windows.open,
            feedbackCloseAt: windows.close,
          },
        },
        context.actorId,
        context.actorRole,
        SEED_ORG_ID,
      );

  const eventId = draft.id;

  if (draft.state === "Draft") {
    await eventService.publish(eventId, context);
    await eventService.openRegistration(eventId, context);
  }

  const seatHolderId = randomUUID();
  await ensureTestParticipant(seatHolderId);
  await registrationService.register(eventId, seatHolderId, {
    actorId: seatHolderId,
    actorRole: "Participant",
  });

  await registrationService.register(eventId, participantId, {
    actorId: participantId,
    actorRole: "Participant",
  });

  return eventId;
}

async function ensureFeedbackFixture(
  participantId: string,
  context: { actorId: string; actorRole: "OrganizerAdmin" },
): Promise<string> {
  const name = `SEED ${SEED_MARKER} feedback`;
  const existingId = await findEventIdByName(name);
  if (existingId) {
    const attended = await getPool().query(
      `SELECT id FROM registrations
       WHERE event_id = $1 AND participant_id = $2 AND state = 'Attended'
       LIMIT 1`,
      [existingId, participantId],
    );
    if (attended.rows.length > 0) {
      return existingId;
    }
  }

  const windows = seedWindows();
  const eventService = new EventService();
  const registrationService = new RegistrationService();
  const checkinService = new CheckinService();

  const draft = existingId
    ? (await findEventById(existingId))!
    : await createEvent(
        {
          name,
          description: "Browser fixture — feedback quick action",
          location: "Feedback Lounge",
          startAt: windows.open,
          endAt: windows.close,
          ruleConfig: {
            capacity: 20,
            waitlistEnabled: false,
            registrationOpenAt: windows.open,
            registrationCloseAt: windows.close,
            checkinOpenAt: windows.open,
            checkinCloseAt: windows.close,
            feedbackOpenAt: windows.open,
            feedbackCloseAt: windows.close,
            feedbackRequired: true,
          },
        },
        context.actorId,
        context.actorRole,
        SEED_ORG_ID,
      );

  const eventId = draft.id;

  if (draft.state === "Draft") {
    await eventService.publish(eventId, context);
    await eventService.openRegistration(eventId, context);
  }

  let registrationId: string | undefined;
  const existingRegistration = await getPool().query<{ id: string }>(
    `SELECT id FROM registrations
     WHERE event_id = $1 AND participant_id = $2
     ORDER BY updated_at DESC
     LIMIT 1`,
    [eventId, participantId],
  );
  registrationId = existingRegistration.rows[0]?.id;

  if (!registrationId) {
    const registered = await registrationService.register(eventId, participantId, {
      actorId: participantId,
      actorRole: "Participant",
    });
    registrationId = registered.registrationId;
  }

  const refreshed = await findEventById(eventId);
  if (refreshed?.state === "RegistrationOpen") {
    await eventService.closeRegistration(eventId, context);
  }

  const afterClose = await findEventById(eventId);
  if (
    afterClose?.state !== "InProgress" &&
    afterClose?.state !== "Completed"
  ) {
    await transitionEventState(eventId, "InProgress", {
      ...context,
      action: "event.started",
    });
  }

  const beforeComplete = await findEventById(eventId);
  if (beforeComplete?.state === "InProgress") {
    await checkinService.staffCheckin(
      eventId,
      { registrationId: registrationId! },
      context,
    );
    await eventService.complete(eventId, context);
  }

  return eventId;
}

export async function runDevSeed(): Promise<DevSeedFixtures> {
  if (cachedFixtures) {
    return cachedFixtures;
  }

  await ensureEventSchema();
  await ensureRegistrationSchema();
  await ensureCheckinSchema();
  await ensureIdempotencySchema();
  await ensureUserSchema();
  await ensureTestOrganizerAdmin(SEED_ORG_ADMIN_ID);

  const participantId = resolveActorId(SEED_PARTICIPANT_SUB);
  await ensureTestParticipant(SEED_PARTICIPANT_SUB);

  const context = {
    actorId: SEED_ORG_ADMIN_ID,
    actorRole: "OrganizerAdmin" as const,
  };

  const [
    bulkRegistrationsEventId,
    staffAssignedEventIds,
    checkinEventId,
    waitlistEventId,
    feedbackEventId,
  ] = await Promise.all([
    ensureBulkRegistrationsEvent(context),
    ensureStaffAssignedEvents(context),
    ensureCheckinFixture(participantId, context),
    ensureWaitlistFixture(participantId, context),
    ensureFeedbackFixture(participantId, context),
  ]);

  cachedFixtures = {
    bulkRegistrationsEventId,
    staffSub: SEED_ORG_STAFF_ID,
    staffAssignedEventIds,
    participantSub: SEED_PARTICIPANT_SUB,
    checkinEventId,
    waitlistEventId,
    feedbackEventId,
  };

  return cachedFixtures;
}
