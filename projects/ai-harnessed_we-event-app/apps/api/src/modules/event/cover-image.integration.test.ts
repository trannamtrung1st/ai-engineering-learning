import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
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

  it("FR-35/FR-36: organizer uploads cover image and participant sees coverImageUrl", async () => {
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

  it("FR-35: replace deletes previous file and updates key", async () => {
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

  it("DELETE /cover-image removes image and clears coverImageUrl", async () => {
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

  it("NFR-18: rejects invalid MIME type and oversized uploads", async () => {
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
});
