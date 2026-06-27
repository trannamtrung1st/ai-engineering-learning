import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, it } from "node:test";

import {
  createDraftEvent,
  transitionEvent,
} from "../helpers/event-factory.js";
import {
  type E2EContext,
  type PaginatedEnvelope,
  apiRequest,
  assertOk,
  createE2EContext,
  destroyE2EContext,
  newIdempotencyKey,
  ORGANIZER_ADMIN_SUB,
  parseJson,
  signDevToken,
  uploadCoverImage,
} from "../helpers/setup.js";

const MINIMAL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

const MINIMAL_JPEG = Buffer.from(
  "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=",
  "base64",
);

const MINIMAL_WEBP = Buffer.from(
  "UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAwA0JaQAA3AA/vuUAAA=",
  "base64",
);

describe("AC-17 — event cover image media (FR-35, FR-36, NFR-18)", () => {
  let ctx: E2EContext;
  let uploadsDir: string;
  let organizerToken: string;

  before(async () => {
    uploadsDir = await mkdtemp(join(tmpdir(), "we-event-e2e-uploads-"));
    process.env.UPLOADS_DIR = uploadsDir;
    ctx = await createE2EContext();
    organizerToken = await signDevToken(ctx.app, ORGANIZER_ADMIN_SUB, "OrganizerAdmin");
  });

  after(async () => {
    await destroyE2EContext(ctx);
    await rm(uploadsDir, { recursive: true, force: true });
  });

  it("TC-FR-35-001 / AC-17 / FR-35: OrganizerAdmin uploads cover image to draft event", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken);

    const uploadResponse = await uploadCoverImage(ctx.app, {
      eventId,
      token: organizerToken,
      filename: "cover.png",
      mimeType: "image/png",
      data: MINIMAL_PNG,
    });
    assert.equal(uploadResponse.statusCode, 200, uploadResponse.body);
    const uploaded = parseJson<{ coverImageUrl: string }>(uploadResponse.body);
    assert.match(uploaded.coverImageUrl, /^\/api\/v1\/media\/events\/.+\.png$/);

    const detailResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: organizerToken,
    });
    assertOk(detailResponse.statusCode, detailResponse.body, "organizer detail");
    const detail = parseJson<{ coverImageUrl: string }>(detailResponse.body);
    assert.equal(detail.coverImageUrl, uploaded.coverImageUrl);
  });

  it("TC-FR-36-001 / TC-FR-36-002 / TC-FR-36-003 / AC-17 / FR-36: participant sees cover on list, detail, and media", async () => {
    const uniqueName = `AC-17 Cover Event ${randomUUID()}`;
    const { eventId } = await createDraftEvent(ctx.app, organizerToken);
    await apiRequest(ctx.app, {
      method: "PATCH",
      path: `/events/${eventId}`,
      token: organizerToken,
      payload: { name: uniqueName },
      idempotencyKey: newIdempotencyKey(),
    });

    const uploadResponse = await uploadCoverImage(ctx.app, {
      eventId,
      token: organizerToken,
      filename: "cover.png",
      mimeType: "image/png",
      data: MINIMAL_PNG,
    });
    assertOk(uploadResponse.statusCode, uploadResponse.body, "upload cover");
    const uploaded = parseJson<{ coverImageUrl: string }>(uploadResponse.body);

    await transitionEvent(ctx.app, organizerToken, eventId, "publish");

    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");

    const listResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events?page=1&pageSize=12&q=${encodeURIComponent(uniqueName)}`,
      token: participantToken,
    });
    assertOk(listResponse.statusCode, listResponse.body, "participant list");
    const list = parseJson<
      PaginatedEnvelope<{ eventId: string; coverImageUrl?: string }>
    >(listResponse.body);
    const listItem = list.items.find((item) => item.eventId === eventId);
    assert.ok(listItem, listResponse.body);
    assert.equal(listItem.coverImageUrl, uploaded.coverImageUrl);

    const detailResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: participantToken,
    });
    assertOk(detailResponse.statusCode, detailResponse.body, "participant detail");
    const detail = parseJson<{ coverImageUrl: string }>(detailResponse.body);
    assert.equal(detail.coverImageUrl, uploaded.coverImageUrl);

    const mediaResponse = await ctx.app.inject({
      method: "GET",
      url: uploaded.coverImageUrl,
    });
    assert.equal(mediaResponse.statusCode, 200, mediaResponse.body);
    assert.equal(mediaResponse.headers["content-type"], "image/png");
    assert.deepEqual(mediaResponse.rawPayload, MINIMAL_PNG);
  });

  it("TC-NFR-18-001 / TC-NFR-18-004 / AC-17 / NFR-18 / FR-35 / FR-36: validated upload served via controlled media path", async () => {
    const { eventId } = await createDraftEvent(ctx.app, organizerToken);

    const uploadResponse = await uploadCoverImage(ctx.app, {
      eventId,
      token: organizerToken,
      filename: "cover.webp",
      mimeType: "image/webp",
      data: MINIMAL_WEBP,
    });
    assert.equal(uploadResponse.statusCode, 200, uploadResponse.body);
    const uploaded = parseJson<{ coverImageUrl: string }>(uploadResponse.body);
    assert.match(uploaded.coverImageUrl, /^\/api\/v1\/media\/events\/.+\.webp$/);
    assert.ok(!uploaded.coverImageUrl.includes(uploadsDir));

    await transitionEvent(ctx.app, organizerToken, eventId, "publish");
    const participantToken = await signDevToken(ctx.app, randomUUID(), "Participant");

    const detailResponse = await apiRequest(ctx.app, {
      method: "GET",
      path: `/events/${eventId}`,
      token: participantToken,
    });
    assertOk(detailResponse.statusCode, detailResponse.body, "participant detail");
    const detail = parseJson<{ coverImageUrl: string }>(detailResponse.body);
    assert.equal(detail.coverImageUrl, uploaded.coverImageUrl);

    const mediaResponse = await ctx.app.inject({
      method: "GET",
      url: uploaded.coverImageUrl,
    });
    assert.equal(mediaResponse.statusCode, 200, mediaResponse.body);
    assert.equal(mediaResponse.headers["content-type"], "image/webp");
    assert.deepEqual(mediaResponse.rawPayload, MINIMAL_WEBP);
  });

  it("TC-NFR-18-007 / AC-17 / NFR-18 / FR-36: each allowed format returns matching Content-Type on media GET", async () => {
    const formats = [
      { filename: "cover.jpg", mimeType: "image/jpeg", data: MINIMAL_JPEG },
      { filename: "cover.png", mimeType: "image/png", data: MINIMAL_PNG },
      { filename: "cover.webp", mimeType: "image/webp", data: MINIMAL_WEBP },
    ] as const;

    for (const format of formats) {
      const { eventId } = await createDraftEvent(ctx.app, organizerToken);
      const uploadResponse = await uploadCoverImage(ctx.app, {
        eventId,
        token: organizerToken,
        filename: format.filename,
        mimeType: format.mimeType,
        data: format.data,
      });
      assert.equal(uploadResponse.statusCode, 200, uploadResponse.body);
      const uploaded = parseJson<{ coverImageUrl: string }>(uploadResponse.body);

      const mediaResponse = await ctx.app.inject({
        method: "GET",
        url: uploaded.coverImageUrl,
      });
      assert.equal(mediaResponse.statusCode, 200, mediaResponse.body);
      assert.equal(mediaResponse.headers["content-type"], format.mimeType);
      assert.deepEqual(mediaResponse.rawPayload, format.data);
    }
  });
});
