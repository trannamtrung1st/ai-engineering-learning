import assert from "node:assert/strict";
import { access, mkdtemp, rm } from "node:fs/promises";
import { constants } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, it } from "node:test";
import type { FastifyInstance } from "fastify";
import { API_BASE_PATH, buildApp } from "../../index.js";
import { initDb, closeDb } from "../../db/pool.js";
import { ensureEventSchema } from "./repository.js";
import { eventService } from "./service.js";
import type { CreateEventInput } from "./types.js";
import { COVER_IMAGE_MAX_BYTES } from "./cover-image.js";

const ACTOR_ID = "00000000-0000-0000-0000-000000000099";

const MINIMAL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

function defaultWindows() {
  const now = Date.now();
  return {
    open: new Date(now + 86_400_000).toISOString(),
    close: new Date(now + 172_800_000).toISOString(),
    regOpen: new Date(now).toISOString(),
    regClose: new Date(now + 86_400_000).toISOString(),
  };
}

function createInput(): CreateEventInput {
  const windows = defaultWindows();
  return {
    name: "Cover Image Test Event",
    description: "Integration test",
    location: "Room A",
    startAt: windows.open,
    endAt: windows.close,
    ruleConfig: {
      capacity: 10,
      waitlistEnabled: false,
      registrationOpenAt: windows.regOpen,
      registrationCloseAt: windows.regClose,
      checkinOpenAt: windows.regOpen,
      checkinCloseAt: windows.regClose,
      feedbackOpenAt: windows.regOpen,
      feedbackCloseAt: windows.regClose,
    },
  };
}

async function signDevToken(
  app: FastifyInstance,
  sub: string,
  role: string,
): Promise<string> {
  const response = await app.inject({
    method: "POST",
    url: `${API_BASE_PATH}/dev/token`,
    payload: { sub, role },
  });
  assert.equal(response.statusCode, 200, response.body);
  return (JSON.parse(response.body) as { token: string }).token;
}

function multipartPayload(
  boundary: string,
  filename: string,
  mimeType: string,
  data: Buffer,
): Buffer {
  const prefix = Buffer.from(
    `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="file"; filename="${filename}"\r\n` +
      `Content-Type: ${mimeType}\r\n\r\n`,
  );
  const suffix = Buffer.from(`\r\n--${boundary}--\r\n`);
  return Buffer.concat([prefix, data, suffix]);
}

describe("event cover image integration", () => {
  let app: FastifyInstance;
  let uploadsDir: string;

  before(async () => {
    uploadsDir = await mkdtemp(join(tmpdir(), "we-event-uploads-"));
    process.env.DATABASE_URL ??=
      "postgresql://we_event:we_event@localhost:5432/we_event";
    process.env.JWT_SECRET ??= "test-jwt-secret";
    process.env.DEV_AUTH_ENABLED = "true";
    process.env.UPLOADS_DIR = uploadsDir;

    await initDb(process.env.DATABASE_URL);
    await ensureEventSchema();
    ({ app } = await buildApp());
  });

  after(async () => {
    await app.close();
    await closeDb();
    await rm(uploadsDir, { recursive: true, force: true });
  });

  it("TC-FR-35-001 / FR-35 / FR-36 / TC-NFR-18-006: organizer uploads cover image and participant sees coverImageUrl", async () => {
    const created = await eventService.create(
      createInput(),
      ACTOR_ID,
      "OrganizerAdmin",
    );
    const adminToken = await signDevToken(app, ACTOR_ID, "OrganizerAdmin");
    const participantToken = await signDevToken(
      app,
      "00000000-0000-0000-0000-000000000088",
      "Participant",
    );

    const boundary = "we-event-cover-boundary";
    const uploadResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload: multipartPayload(boundary, "cover.png", "image/png", MINIMAL_PNG),
    });

    assert.equal(uploadResponse.statusCode, 200, uploadResponse.body);
    const uploaded = JSON.parse(uploadResponse.body) as {
      eventId: string;
      coverImageUrl: string;
    };
    assert.match(uploaded.coverImageUrl, /^\/api\/v1\/media\/events\/.+\.png$/);

    const detailResponse = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${created.eventId}`,
      headers: { authorization: `Bearer ${participantToken}` },
    });
    assert.equal(detailResponse.statusCode, 404);

    await eventService.publish(created.eventId, {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    });

    const publishedDetail = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${created.eventId}`,
      headers: { authorization: `Bearer ${participantToken}` },
    });
    assert.equal(publishedDetail.statusCode, 200, publishedDetail.body);
    const detail = JSON.parse(publishedDetail.body) as { coverImageUrl: string };
    assert.equal(detail.coverImageUrl, uploaded.coverImageUrl);

    const mediaResponse = await app.inject({
      method: "GET",
      url: uploaded.coverImageUrl,
    });
    assert.equal(mediaResponse.statusCode, 200, mediaResponse.body);
    assert.equal(mediaResponse.headers["content-type"], "image/png");
    assert.deepEqual(mediaResponse.rawPayload, MINIMAL_PNG);
  });

  it("TC-FR-35-002 / TC-FR-36-015 / FR-35: replace deletes previous file and updates key", async () => {
    const created = await eventService.create(
      createInput(),
      ACTOR_ID,
      "OrganizerAdmin",
    );
    const adminToken = await signDevToken(app, ACTOR_ID, "OrganizerAdmin");
    const boundary = "we-event-replace-boundary";

    const firstUpload = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload: multipartPayload(boundary, "first.png", "image/png", MINIMAL_PNG),
    });
    assert.equal(firstUpload.statusCode, 200, firstUpload.body);
    const first = JSON.parse(firstUpload.body) as { coverImageUrl: string };

    const secondUpload = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload: multipartPayload(boundary, "second.webp", "image/webp", MINIMAL_PNG),
    });
    assert.equal(secondUpload.statusCode, 200, secondUpload.body);
    const second = JSON.parse(secondUpload.body) as { coverImageUrl: string };
    assert.notEqual(second.coverImageUrl, first.coverImageUrl);

    const staleMedia = await app.inject({
      method: "GET",
      url: first.coverImageUrl,
    });
    assert.equal(staleMedia.statusCode, 404);
  });

  it("TC-FR-35-003 / TC-NFR-18-011 / FR-35: DELETE /cover-image removes image and clears coverImageUrl", async () => {
    const created = await eventService.create(
      createInput(),
      ACTOR_ID,
      "OrganizerAdmin",
    );
    const adminToken = await signDevToken(app, ACTOR_ID, "OrganizerAdmin");
    const boundary = "we-event-delete-boundary";

    const uploadResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload: multipartPayload(boundary, "cover.png", "image/png", MINIMAL_PNG),
    });
    const uploaded = JSON.parse(uploadResponse.body) as { coverImageUrl: string };

    const deleteResponse = await app.inject({
      method: "DELETE",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: { authorization: `Bearer ${adminToken}` },
    });
    assert.equal(deleteResponse.statusCode, 200, deleteResponse.body);
    const deleted = JSON.parse(deleteResponse.body) as { coverImageUrl?: string };
    assert.equal(deleted.coverImageUrl, undefined);

    const mediaResponse = await app.inject({
      method: "GET",
      url: uploaded.coverImageUrl,
    });
    assert.equal(mediaResponse.statusCode, 404);
  });

  it("TC-FR-35-007 / TC-FR-35-008 / TC-NFR-18-005 / NFR-18: rejects invalid MIME type and oversized uploads", async () => {
    const created = await eventService.create(
      createInput(),
      ACTOR_ID,
      "OrganizerAdmin",
    );
    const adminToken = await signDevToken(app, ACTOR_ID, "OrganizerAdmin");
    const boundary = "we-event-invalid-boundary";

    const invalidMime = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload: multipartPayload(
        boundary,
        "cover.gif",
        "image/gif",
        MINIMAL_PNG,
      ),
    });
    assert.equal(invalidMime.statusCode, 400);
    assert.equal(
      (JSON.parse(invalidMime.body) as { error: { code: string } }).error.code,
      "INVALID_INPUT",
    );

    const oversized = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload: multipartPayload(
        boundary,
        "huge.png",
        "image/png",
        Buffer.alloc(COVER_IMAGE_MAX_BYTES + 1, 1),
      ),
    });
    assert.equal(oversized.statusCode, 400);
  });

  it("TC-FR-36-005 / TC-NFR-18-003 / FR-36: list and detail expose coverImageUrl on controlled media path", async () => {
    const uniqueName = `Cover Image List Test ${Date.now()}`;
    const input = { ...createInput(), name: uniqueName };
    const created = await eventService.create(
      input,
      ACTOR_ID,
      "OrganizerAdmin",
    );
    await eventService.publish(created.eventId, {
      actorId: ACTOR_ID,
      actorRole: "OrganizerAdmin",
    });

    const adminToken = await signDevToken(app, ACTOR_ID, "OrganizerAdmin");
    const boundary = "we-event-list-boundary";
    const uploadResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload: multipartPayload(boundary, "cover.png", "image/png", MINIMAL_PNG),
    });
    assert.equal(uploadResponse.statusCode, 200, uploadResponse.body);
    const uploaded = JSON.parse(uploadResponse.body) as { coverImageUrl: string };
    assert.match(uploaded.coverImageUrl, /^\/api\/v1\/media\/events\/.+\.png$/);

    const listResponse = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events?page=1&pageSize=12&q=${encodeURIComponent(uniqueName)}`,
      headers: { authorization: `Bearer ${adminToken}` },
    });
    assert.equal(listResponse.statusCode, 200, listResponse.body);
    const list = JSON.parse(listResponse.body) as {
      items: Array<{ eventId: string; coverImageUrl?: string }>;
    };
    const listItem = list.items.find((item) => item.eventId === created.eventId);
    assert.ok(listItem, listResponse.body);
    assert.equal(listItem.coverImageUrl, uploaded.coverImageUrl);

    const detailResponse = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/events/${created.eventId}`,
      headers: { authorization: `Bearer ${adminToken}` },
    });
    const detail = JSON.parse(detailResponse.body) as { coverImageUrl: string };
    assert.equal(detail.coverImageUrl, uploaded.coverImageUrl);
  });

  it("TC-NFR-18-002 / NFR-18: uploaded cover file persisted under configured uploads directory", async () => {
    const created = await eventService.create(
      createInput(),
      ACTOR_ID,
      "OrganizerAdmin",
    );
    const adminToken = await signDevToken(app, ACTOR_ID, "OrganizerAdmin");
    const boundary = "we-event-fs-boundary";

    const uploadResponse = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload: multipartPayload(boundary, "cover.png", "image/png", MINIMAL_PNG),
    });
    assert.equal(uploadResponse.statusCode, 200, uploadResponse.body);
    const uploaded = JSON.parse(uploadResponse.body) as { coverImageUrl: string };
    const key = uploaded.coverImageUrl.replace(`${API_BASE_PATH}/media/events/`, "");
    const filePath = join(uploadsDir, "events", key);
    await access(filePath, constants.R_OK);
  });

  it("TC-FR-35-010 / TC-FR-35-011 / TC-FR-35-012 / FR-35: cover mutations require OrganizerAdmin", async () => {
    const created = await eventService.create(
      createInput(),
      ACTOR_ID,
      "OrganizerAdmin",
    );
    const adminToken = await signDevToken(app, ACTOR_ID, "OrganizerAdmin");
    const participantToken = await signDevToken(
      app,
      "00000000-0000-0000-0000-000000000077",
      "Participant",
    );
    const staffToken = await signDevToken(
      app,
      "00000000-0000-0000-0000-000000000066",
      "OrganizerStaff",
    );
    const boundary = "we-event-rbac-boundary";
    const payload = multipartPayload(
      boundary,
      "cover.png",
      "image/png",
      MINIMAL_PNG,
    );

    const unauthenticated = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: { "content-type": `multipart/form-data; boundary=${boundary}` },
      payload,
    });
    assert.equal(unauthenticated.statusCode, 401);

    const participantUpload = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${participantToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload,
    });
    assert.equal(participantUpload.statusCode, 403);

    const staffUpload = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${staffToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload,
    });
    assert.equal(staffUpload.statusCode, 403);

    const adminUpload = await app.inject({
      method: "POST",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: {
        authorization: `Bearer ${adminToken}`,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload,
    });
    assert.equal(adminUpload.statusCode, 200, adminUpload.body);

    const participantDelete = await app.inject({
      method: "DELETE",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: { authorization: `Bearer ${participantToken}` },
    });
    assert.equal(participantDelete.statusCode, 403);

    const staffDelete = await app.inject({
      method: "DELETE",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: { authorization: `Bearer ${staffToken}` },
    });
    assert.equal(staffDelete.statusCode, 403);
  });

  it("TC-FR-35-016 / FR-35: DELETE cover-image on event without cover succeeds without side effects", async () => {
    const created = await eventService.create(
      createInput(),
      ACTOR_ID,
      "OrganizerAdmin",
    );
    const adminToken = await signDevToken(app, ACTOR_ID, "OrganizerAdmin");

    const deleteResponse = await app.inject({
      method: "DELETE",
      url: `${API_BASE_PATH}/events/${created.eventId}/cover-image`,
      headers: { authorization: `Bearer ${adminToken}` },
    });
    assert.equal(deleteResponse.statusCode, 200, deleteResponse.body);
    const body = JSON.parse(deleteResponse.body) as { coverImageUrl?: string };
    assert.equal(body.coverImageUrl, undefined);
  });

  it("TC-FR-35-017 / TC-NFR-18-010 / NFR-18: media route rejects path traversal and invalid keys", async () => {
    const traversal = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/media/events/../etc/passwd`,
    });
    assert.equal(traversal.statusCode, 404);

    const invalidKey = await app.inject({
      method: "GET",
      url: `${API_BASE_PATH}/media/events/not-a-valid-key`,
    });
    assert.equal(invalidKey.statusCode, 404);
  });
});
