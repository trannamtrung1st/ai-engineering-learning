import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import {
  createDraftEvent,
  createRegistrationOpenEvent,
  registerParticipant,
  transitionEvent,
} from "../helpers/event-factory.js";
import {
  type E2EContext,
  type ErrorEnvelope,
  type PaginatedEnvelope,
  apiRequest,
  assertOk,
  createE2EContext,
  destroyE2EContext,
  ORGANIZER_ADMIN_SUB,
  parseJson,
  signDevToken,
} from "../helpers/setup.js";

interface EventListItem {
  eventId: string;
  name: string;
  state: string;
  startAt: string;
  location: string;
}

interface MyRegistrationItem {
  registrationId: string;
  eventId: string;
  eventName: string;
  state: string;
  waitlistPosition: number | null;
}

async function publishAndOpen(
  ctx: E2EContext,
  organizerToken: string,
  eventId: string,
): Promise<void> {
  await transitionEvent(ctx.app, organizerToken, eventId, "publish");
  await transitionEvent(ctx.app, organizerToken, eventId, "open-registration");
}

async function createVisibleEvent(
  ctx: E2EContext,
  organizerToken: string,
  options: {
    name: string;
    description?: string;
    location?: string;
    targetState?: "RegistrationOpen" | "RegistrationClosed";
  },
): Promise<string> {
  const { eventId } = await createDraftEvent(ctx.app, organizerToken);
  const patchResponse = await apiRequest(ctx.app, {
    method: "PATCH",
    path: `/events/${eventId}`,
    token: organizerToken,
    payload: {
      name: options.name,
      description: options.description ?? "E2E discovery fixture",
      location: options.location ?? "Room E2E",
    },
  });
  assertOk(patchResponse.statusCode, patchResponse.body, "patch event");

  await publishAndOpen(ctx, organizerToken, eventId);

  if (options.targetState === "RegistrationClosed") {
    await transitionEvent(ctx.app, organizerToken, eventId, "close-registration");
  }

  return eventId;
}

describe("Participant discovery — event browse filters and sort (FR-28, AC-18a, AC-18b, AC-18d)", () => {
  let ctx: E2EContext;
  let organizerToken: string;
  let participantToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
    participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("TC-FR-28-003 / FR-28 / AC-18a: participant searches events by name, location, and description", async () => {
    const marker = randomUUID();
    const nameToken = `Campus Workshop Alpha ${marker}`;
    const locationToken = `Building C Room 204 ${marker}`;
    const descriptionToken = `UniqueDescriptionToken ${marker}`;

    const nameEventId = await createVisibleEvent(ctx, organizerToken, { name: nameToken });
    const locationEventId = await createVisibleEvent(ctx, organizerToken, {
      name: `Other ${marker}`,
      location: locationToken,
    });
    const descriptionEventId = await createVisibleEvent(ctx, organizerToken, {
      name: `Another ${marker}`,
      description: descriptionToken,
    });
    await createVisibleEvent(ctx, organizerToken, { name: `Unrelated ${randomUUID()}` });

    const searches: Array<{ query: string; eventId: string }> = [
      { query: nameToken, eventId: nameEventId },
      { query: locationToken, eventId: locationEventId },
      { query: descriptionToken, eventId: descriptionEventId },
    ];

    for (const { query, eventId } of searches) {
      const response = await apiRequest(ctx.app, {
        method: "GET",
        path: `/events?q=${encodeURIComponent(query)}&page=1&pageSize=12`,
        token: participantToken,
      });
      assertOk(response.statusCode, response.body, `search q=${query}`);
      const body = parseJson<PaginatedEnvelope<EventListItem>>(response.body);
      assert.ok(body.items.some((item) => item.eventId === eventId), `expected ${eventId} for ${query}`);
    }
  });

  it("TC-FR-28-004 / FR-28 / AC-18a: participant filters event browse by state", async () => {
    const marker = randomUUID();
    const openName = `OpenFilter ${marker}`;
    const closedName = `ClosedFilter ${marker}`;

    await createVisibleEvent(ctx, organizerToken, {
      name: openName,
      targetState: "RegistrationOpen",
    });
    await createVisibleEvent(ctx, organizerToken, {
      name: closedName,
      targetState: "RegistrationClosed",
    });

    const openResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?state=RegistrationOpen&q=${encodeURIComponent(marker)}&page=1&pageSize=12`,
      token: participantToken,
    });
    assertOk(openResponse.statusCode, openResponse.body, "RegistrationOpen filter");
    const openBody = parseJson<PaginatedEnvelope<EventListItem>>(openResponse.body);
    assert.ok(openBody.items.some((item) => item.name === openName));
    assert.ok(openBody.items.every((item) => item.state === "RegistrationOpen"));

    const closedResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?state=RegistrationClosed&q=${encodeURIComponent(marker)}&page=1&pageSize=12`,
      token: participantToken,
    });
    assertOk(closedResponse.statusCode, closedResponse.body, "RegistrationClosed filter");
    const closedBody = parseJson<PaginatedEnvelope<EventListItem>>(closedResponse.body);
    assert.ok(closedBody.items.some((item) => item.name === closedName));
    assert.ok(closedBody.items.every((item) => item.state === "RegistrationClosed"));
  });

  it("TC-FR-28-005 / FR-28 / FR-31 / AC-18a: combined search, state filter, and pagination", async () => {
    const marker = `workshop-${randomUUID()}`;
    const createdIds: string[] = [];

    for (let index = 0; index < 13; index += 1) {
      const eventId = await createVisibleEvent(ctx, organizerToken, {
        name: `${marker} Workshop ${index}`,
        targetState: "RegistrationOpen",
      });
      createdIds.push(eventId);
    }

    await createVisibleEvent(ctx, organizerToken, {
      name: `${marker} Seminar`,
      targetState: "RegistrationClosed",
    });

    const page1Response = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?q=${encodeURIComponent(marker)}&state=RegistrationOpen&page=1&pageSize=12&sort=startAt:asc`,
      token: participantToken,
    });
    assertOk(page1Response.statusCode, page1Response.body, "combined page 1");
    const page1 = parseJson<PaginatedEnvelope<EventListItem>>(page1Response.body);
    assert.equal(page1.page, 1);
    assert.equal(page1.pageSize, 12);
    assert.ok(page1.total >= 13);
    assert.equal(page1.items.length, 12);
    assert.ok(page1.items.every((item) => item.state === "RegistrationOpen"));
    assert.ok(page1.items.every((item) => item.name.toLowerCase().includes("workshop")));

    const page2Response = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?q=${encodeURIComponent(marker)}&state=RegistrationOpen&page=2&pageSize=12&sort=startAt:asc`,
      token: participantToken,
    });
    assertOk(page2Response.statusCode, page2Response.body, "combined page 2");
    const page2 = parseJson<PaginatedEnvelope<EventListItem>>(page2Response.body);
    assert.equal(page2.page, 2);
    assert.equal(page2.total, page1.total);
    assert.ok(page2.items.length >= 1);
    assert.ok(page2.items.every((item) => item.state === "RegistrationOpen"));

    const page1Ids = new Set(page1.items.map((item) => item.eventId));
    assert.ok(page2.items.every((item) => !page1Ids.has(item.eventId)));
  });

  it("TC-FR-28-013 / FR-28 / AC-18a: invalid state filter returns 400 INVALID_INPUT", async () => {
    const response = await apiRequest(ctx.app, {
      method: "GET",
      path: "/events?state=NotARealState&page=1&pageSize=12",
      token: participantToken,
    });
    assert.equal(response.statusCode, 400);
    const body = parseJson<ErrorEnvelope>(response.body);
    assert.equal(body.error.code, "INVALID_INPUT");
  });

  it("TC-FR-28-019 / FR-28 / AC-18b: invalid sort parameter returns 400 INVALID_INPUT", async () => {
    for (const sort of ["notAField:asc", "startAt:sideways"]) {
      const response = await apiRequest(ctx.app, {
        method: "GET",
        path: `/events?sort=${encodeURIComponent(sort)}&page=1&pageSize=12`,
        token: participantToken,
      });
      assert.equal(response.statusCode, 400, sort);
      const body = parseJson<ErrorEnvelope>(response.body);
      assert.equal(body.error.code, "INVALID_INPUT");
    }
  });

  it("TC-FR-28-020 / FR-28 / AC-18d: sort=updatedAt:desc orders events by updatedAt descending", async () => {
    const marker = randomUUID();

    const { eventId: firstId } = await createDraftEvent(ctx.app, organizerToken);
    let patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${firstId}`,
      token: organizerToken,
      payload: { name: `SortA ${marker}` },
    });
    assertOk(patchResponse.statusCode, patchResponse.body, "patch first draft");
    await transitionEvent(ctx.app, organizerToken, firstId, "publish");

    const { eventId: secondId } = await createDraftEvent(ctx.app, organizerToken);
    patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${secondId}`,
      token: organizerToken,
      payload: { name: `SortB ${marker}` },
    });
    assertOk(patchResponse.statusCode, patchResponse.body, "patch second draft");
    await transitionEvent(ctx.app, organizerToken, secondId, "publish");

    patchResponse = await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${firstId}`,
      token: organizerToken,
      payload: { name: `SortA updated ${marker}` },
    });
    assertOk(patchResponse.statusCode, patchResponse.body, "patch first published");

    const response = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?q=${encodeURIComponent(marker)}&state=Published&sort=updatedAt:desc&page=1&pageSize=12`,
      token: participantToken,
    });
    assertOk(response.statusCode, response.body, "updatedAt:desc sort");
    const body = parseJson<PaginatedEnvelope<EventListItem>>(response.body);
    assert.equal(body.items.length, 2);

    const firstIndex = body.items.findIndex((item) => item.eventId === firstId);
    const secondIndex = body.items.findIndex((item) => item.eventId === secondId);
    assert.ok(firstIndex >= 0 && secondIndex >= 0);
    assert.ok(firstIndex < secondIndex, "patched event should appear before older sibling");
  });
});

describe("Participant discovery — my registrations filters and sort (FR-29, AC-18b, AC-18c)", () => {
  let ctx: E2EContext;
  let organizerToken: string;

  before(async () => {
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
  });

  it("TC-FR-29-004 / FR-29 / AC-18c: participant filters my registrations by state server-side", async () => {
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");

    const registeredEvent = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    const waitlistEvent = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 1,
      waitlistEnabled: true,
    });

    await registerParticipant(ctx.app, participantToken, registeredEvent.eventId);

    const seatHolderToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    await registerParticipant(ctx.app, seatHolderToken, waitlistEvent.eventId);
    const waitlisted = await registerParticipant(
      ctx.app,
      participantToken,
      waitlistEvent.eventId,
    );
    assert.equal(waitlisted.state, "Waitlisted");

    const registeredResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: "/me/registrations?state=Registered&page=1&pageSize=20",
      token: participantToken,
    });
    assertOk(registeredResponse.statusCode, registeredResponse.body, "Registered filter");
    const registeredBody = parseJson<PaginatedEnvelope<MyRegistrationItem>>(
      registeredResponse.body,
    );
    assert.ok(registeredBody.items.length >= 1);
    assert.ok(registeredBody.items.every((item) => item.state === "Registered"));
    assert.ok(
      registeredBody.items.some((item) => item.eventId === registeredEvent.eventId),
    );

    const waitlistedResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: "/me/registrations?state=Waitlisted&page=1&pageSize=20",
      token: participantToken,
    });
    assertOk(waitlistedResponse.statusCode, waitlistedResponse.body, "Waitlisted filter");
    const waitlistedBody = parseJson<PaginatedEnvelope<MyRegistrationItem>>(
      waitlistedResponse.body,
    );
    assert.ok(waitlistedBody.items.length >= 1);
    assert.ok(waitlistedBody.items.every((item) => item.state === "Waitlisted"));
    assert.ok(
      waitlistedBody.items.some((item) => item.eventId === waitlistEvent.eventId),
    );
    assert.ok(
      waitlistedBody.items.every(
        (item) => item.state !== "Registered" || item.waitlistPosition === null,
      ),
    );
    const waitlistedRow = waitlistedBody.items.find(
      (item) => item.eventId === waitlistEvent.eventId,
    );
    assert.ok(waitlistedRow?.waitlistPosition);
  });

  it("TC-FR-29-013 / FR-29 / AC-18c: state filter with no matches returns empty items", async () => {
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    await registerParticipant(ctx.app, participantToken, eventId);

    const response = await apiRequest(ctx.app, {
      method: "GET",
      path: "/me/registrations?state=Waitlisted&page=1&pageSize=20",
      token: participantToken,
    });
    assertOk(response.statusCode, response.body, "empty Waitlisted filter");
    const body = parseJson<PaginatedEnvelope<MyRegistrationItem>>(response.body);
    assert.deepEqual(body.items, []);
    assert.equal(body.total, 0);
    assert.equal(body.page, 1);
    assert.equal(body.pageSize, 20);
  });

  it("TC-FR-29-019 / FR-29 / AC-18b: invalid sort on my registrations returns 400 INVALID_INPUT", async () => {
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");
    const { eventId } = await createRegistrationOpenEvent(ctx.app, organizerToken, {
      capacity: 5,
    });
    await registerParticipant(ctx.app, participantToken, eventId);

    for (const sort of ["notAField:asc", "updatedAt:sideways"]) {
      const response = await apiRequest(ctx.app, {
        method: "GET",
        path: `/me/registrations?sort=${encodeURIComponent(sort)}&page=1&pageSize=20`,
        token: participantToken,
      });
      assert.equal(response.statusCode, 400, sort);
      const body = parseJson<ErrorEnvelope>(response.body);
      assert.equal(body.error.code, "INVALID_INPUT");
    }
  });
});
