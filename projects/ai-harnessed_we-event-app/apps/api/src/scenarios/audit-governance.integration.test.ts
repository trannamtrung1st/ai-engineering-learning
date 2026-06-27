import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import type { FastifyInstance } from "fastify";

import { API_BASE_PATH, buildApp } from "../index.js";
import { ensureAuditSchema } from "../modules/audit/repository.js";
import { ensureIdempotencySchema } from "../idempotency/index.js";
import {
  createEvent,
  ensureEventSchema,
  transitionEventState,
  updateEvent,
} from "../modules/event/repository.js";
import type { EventWithConfig } from "../modules/event/types.js";
import { ensureRegistrationSchema } from "../modules/registration/repository.js";
import { registrationService } from "../modules/registration/service.js";
import {
  ensureTestOrganizerAdmin,
  ensureTestParticipant,
  ensureTestUser,
} from "../test-helpers/participant-user.js";

const ORG_ID = "00000000-0000-0000-0000-000000000001";
const ORGANIZER_ID = "00000000-0000-0000-0000-000000000099";

function defaultWindows() {
  const now = Date.now();
  return {
    open: new Date(now - 3_600_000).toISOString(),
    close: new Date(now + 86_400_000).toISOString(),
  };
}

async function createRegistrationOpenEvent(options: {
  capacity: number;
}): Promise<EventWithConfig> {
  const windows = defaultWindows();
  const draft = await createEvent(
    {
      name: `Audit HTTP Event ${randomUUID()}`,
      startAt: windows.open,
      endAt: windows.close,
      ruleConfig: {
        capacity: options.capacity,
        waitlistEnabled: false,
        registrationOpenAt: windows.open,
        registrationCloseAt: windows.close,
        checkinOpenAt: windows.open,
        checkinCloseAt: windows.close,
        feedbackOpenAt: windows.open,
        feedbackCloseAt: windows.close,
      },
    },
    ORGANIZER_ID,
    "OrganizerAdmin",
    ORG_ID,
  );

  const transitionContext = {
    actorId: ORGANIZER_ID,
    actorRole: "OrganizerAdmin",
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
    throw new Error("Failed to open registration for audit HTTP scenario");
  }
  return open;
}

async function signDevToken(
  app: FastifyInstance,
  sub: string,
  role: string,
  assignedEventIds: string[] = [],
): Promise<string> {
  const response = await app.inject({
    method: "POST",
    url: `${API_BASE_PATH}/dev/token`,
    payload: { sub, role, assignedEventIds },
  });
  assert.equal(response.statusCode, 200, response.body);
  return (JSON.parse(response.body) as { token: string }).token;
}

function parseError(body: string) {
  return JSON.parse(body) as {
    error: { code: string; message: string };
  };
}

describe("audit HTTP scenario", () => {
  let app: FastifyInstance;
  let eventId: string;
  let adminToken: string;
  let staffToken: string;
  let participantToken: string;

  before(async () => {
    process.env.DATABASE_URL ??=
      "postgresql://we_event:we_event@localhost:5432/we_event";
    process.env.JWT_SECRET ??= "test-jwt-secret";
    process.env.DEV_AUTH_ENABLED = "true";

    ({ app } = await buildApp());
    await ensureEventSchema();
    await ensureAuditSchema();
    await ensureRegistrationSchema();
    await ensureIdempotencySchema();
    await ensureTestOrganizerAdmin(ORGANIZER_ID);

    const event = await createRegistrationOpenEvent({ capacity: 5 });
    eventId = event.id;

    await updateEvent(
      eventId,
      {
        ruleConfig: { capacity: 8 },
        reasonCode: "CAPACITY_CHANGE",
        reasonText: "HTTP audit scenario",
      },
      ORGANIZER_ID,
      "OrganizerAdmin",
    );

    const participantId = randomUUID();
    await ensureTestParticipant(participantId);
    await registrationService.register(eventId, participantId, {
      actorId: participantId,
      actorRole: "Participant",
    });

    adminToken = await signDevToken(app, ORGANIZER_ID, "OrganizerAdmin");
    await ensureTestUser(
      "00000000-0000-0000-0000-000000000088",
      "OrganizerStaff",
      { assignedEventIds: [eventId] },
    );
    staffToken = await signDevToken(
      app,
      "00000000-0000-0000-0000-000000000088",
      "OrganizerStaff",
      [eventId],
    );
    participantToken = await signDevToken(app, participantId, "Participant");
  });

  after(async () => {
    await app.close();
  });

  it("AC-11: OrganizerAdmin can list audit logs with paginated envelope", async () => {
    const response = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${eventId}/audit-logs?entityType=EventRuleConfig&page=1&pageSize=5`,
      headers: { authorization: `Bearer ${adminToken}` },
    });

    assert.equal(response.statusCode, 200, response.body);
    const body = JSON.parse(response.body) as {
      items: Array<{ action: string; reasonCode: string }>;
      page: number;
      pageSize: number;
      total: number;
      totalPages: number;
    };

    assert.equal(body.page, 1);
    assert.equal(body.pageSize, 5);
    assert.ok(body.total >= 1);
    assert.ok(body.totalPages >= 1);

    const ruleChange = body.items.find(
      (entry) => entry.action === "event.rule_config.updated",
    );
    assert.ok(ruleChange);
    assert.equal(ruleChange.reasonCode, "CAPACITY_CHANGE");
  });

  it("FR-25, FR-23: OrganizerStaff cannot access audit logs but can read status history", async () => {
    const denied = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${eventId}/audit-logs`,
      headers: { authorization: `Bearer ${staffToken}` },
    });
    assert.equal(denied.statusCode, 403);
    assert.equal(parseError(denied.body).error.code, "FORBIDDEN");

    const allowed = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${eventId}/status-history?page=1&pageSize=10`,
      headers: { authorization: `Bearer ${staffToken}` },
    });
    assert.equal(allowed.statusCode, 200, allowed.body);

    const history = JSON.parse(allowed.body) as {
      items: Array<{ action: string }>;
      page: number;
      pageSize: number;
      total: number;
      totalPages: number;
    };
    assert.equal(history.page, 1);
    assert.equal(history.pageSize, 10);
    assert.ok(history.total >= 1);
    assert.ok(
      history.items.some((entry) => entry.action === "registration.accepted"),
    );
  });

  it("AC-12: status history returns registration transitions over HTTP", async () => {
    const response = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${eventId}/status-history?sort=createdAt:asc&pageSize=20`,
      headers: { authorization: `Bearer ${adminToken}` },
    });

    assert.equal(response.statusCode, 200, response.body);
    const history = JSON.parse(response.body) as {
      items: Array<{ action: string; afterState: string | null }>;
    };

    const accepted = history.items.find(
      (entry) => entry.action === "registration.accepted",
    );
    assert.ok(accepted);
    assert.equal(accepted.afterState, "Registered");
  });

  it("AC-13: invalid pagination returns INVALID_PAGINATION", async () => {
    const response = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${eventId}/audit-logs?page=0`,
      headers: { authorization: `Bearer ${adminToken}` },
    });

    assert.equal(response.statusCode, 400);
    assert.equal(parseError(response.body).error.code, "INVALID_PAGINATION");
  });

  it("participants cannot access audit or status history routes", async () => {
    const auditDenied = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${eventId}/audit-logs`,
      headers: { authorization: `Bearer ${participantToken}` },
    });
    assert.equal(auditDenied.statusCode, 403);

    const historyDenied = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${eventId}/status-history`,
      headers: { authorization: `Bearer ${participantToken}` },
    });
    assert.equal(historyDenied.statusCode, 403);
  });
});
