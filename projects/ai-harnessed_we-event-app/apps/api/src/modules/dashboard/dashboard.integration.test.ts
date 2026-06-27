import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import { closeDb, initDb } from "../../db/pool.js";
import { ensureIdempotencySchema } from "../../idempotency/index.js";
import { checkinService } from "../checkin/service.js";
import { ensureCheckinSchema } from "../checkin/repository.js";
import {
  createEvent,
  ensureEventSchema,
  transitionEventState,
} from "../event/repository.js";
import type { EventWithConfig } from "../event/types.js";
import {
  createRegistration,
  ensureRegistrationSchema,
  findRegistrationById,
} from "../registration/repository.js";
import { registrationService } from "../registration/service.js";
import { dashboardService } from "./service.js";
import { ensureDashboardSchema } from "./repository.js";
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

async function createCheckinableEvent(): Promise<{
  event: EventWithConfig;
  participantId: string;
  registrationId: string;
}> {
  const windows = eventWindows();
  const participantId = randomUUID();
  await ensureTestParticipant(participantId);

  const draft = await createEvent(
    {
      name: `Dashboard Checkin ${randomUUID()}`,
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
    throw new Error("Failed to start dashboard test event");
  }

  return {
    event: inProgress,
    participantId,
    registrationId: registered.registrationId,
  };
}

describe("NFR-06 / FR-22 event dashboard integration", () => {
  before(async () => {
    const databaseUrl =
      process.env.DATABASE_URL ??
      "postgresql://we_event:we_event@localhost:5432/we_event";
    await initDb(databaseUrl);
    await ensureEventSchema();
    await ensureRegistrationSchema();
    await ensureCheckinSchema();
    await ensureDashboardSchema();
    await ensureIdempotencySchema();
    await ensureTestOrganizerAdmin(ORG_ADMIN_ID);
  });

  after(async () => {
    await closeDb();
  });

  it("TC-NFR-06-007 / FR-22: dashboard check-in KPI reflects new check-in (AC-05)", async () => {
    const { event, registrationId } = await createCheckinableEvent();

    const baseline = await dashboardService.getEventDashboard(event.id);
    assert.equal(baseline.checkedIn, 0);
    assert.equal(baseline.registeredSeats, 1);

    const checkin = await checkinService.staffCheckin(
      event.id,
      { registrationId },
      { actorId: ORG_ADMIN_ID, actorRole: "OrganizerAdmin" },
    );
    assert.equal(checkin.registrationState, "CheckedIn");

    const registration = await findRegistrationById(registrationId);
    assert.equal(registration?.state, "CheckedIn");

    const updated = await dashboardService.getEventDashboard(event.id);
    assert.equal(updated.checkedIn, 1);
    assert.equal(updated.registeredSeats, 0);
    assert.equal(updated.waitlist, baseline.waitlist);
  });

  it("FR-22: dashboard registration count matches paginated registrations list total", async () => {
    const windows = eventWindows();
    const draft = await createEvent(
      {
        name: `Dashboard Count ${randomUUID()}`,
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

    const participantA = randomUUID();
    const participantB = randomUUID();
    await ensureTestParticipant(participantA);
    await ensureTestParticipant(participantB);

    await createRegistration(draft.id, participantA, {
      actorId: participantA,
      actorRole: "Participant",
    });
    await createRegistration(draft.id, participantB, {
      actorId: participantB,
      actorRole: "Participant",
    });

    const dashboard = await dashboardService.getEventDashboard(draft.id);
    const list = await registrationService.listRegistrations(draft.id, {
      page: "1",
      pageSize: "1",
    });

    assert.equal(dashboard.registrations, list.total);
    assert.equal(dashboard.registrations, 2);
  });

  it("TC-FR-22-006: dashboard exposes feedback policy and mandatory outstanding count", async () => {
    const windows = eventWindows();
    const draft = await createEvent(
      {
        name: `Dashboard Feedback ${randomUUID()}`,
        startAt: windows.open,
        endAt: windows.close,
        ruleConfig: {
          capacity: 10,
          waitlistEnabled: false,
          registrationOpenAt: windows.open,
          registrationCloseAt: windows.close,
          checkinOpenAt: windows.open,
          checkinCloseAt: windows.close,
          feedbackRequired: true,
          feedbackOpenAt: windows.open,
          feedbackCloseAt: windows.close,
        },
      },
      ORG_ADMIN_ID,
      "OrganizerAdmin",
      ORG_ID,
    );

    const dashboard = await dashboardService.getEventDashboard(draft.id);

    assert.equal(dashboard.feedbackSubmitted, 0);
    assert.equal(dashboard.feedbackRequired, true);
    assert.equal(dashboard.mandatoryFeedbackOutstanding, 0);
  });
});
