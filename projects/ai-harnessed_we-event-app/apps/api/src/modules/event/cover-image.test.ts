import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ApiError } from "../../errors/api-error.js";
import {
  ALLOWED_COVER_IMAGE_MIME_TYPES,
  buildCoverImageKey,
  buildCoverImageUrl,
  COVER_IMAGE_MAX_BYTES,
  extensionForMime,
  validateCoverImage,
} from "./cover-image.js";

const EVENT_ID = "00000000-0000-0000-0000-000000000010";
const FILE_ID = "00000000-0000-0000-0000-000000000020";

describe("cover image validation", () => {
  it("TC-NFR-18-001 / NFR-18: accepts allowed MIME types within size limit", () => {
    for (const mimeType of ALLOWED_COVER_IMAGE_MIME_TYPES) {
      assert.doesNotThrow(() => validateCoverImage(mimeType, 1024));
      assert.equal(extensionForMime(mimeType), mimeType === "image/jpeg" ? "jpg" : mimeType.split("/")[1]);
    }
  });

  it("TC-FR-35-007 / NFR-18: rejects disallowed MIME types", () => {
    assert.throws(
      () => validateCoverImage("image/gif", 100),
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === "INVALID_INPUT" &&
        error.statusCode === 400,
    );
  });

  it("TC-FR-35-008 / TC-NFR-18-005 / NFR-18: rejects files over 5 MB", () => {
    assert.throws(
      () => validateCoverImage("image/png", COVER_IMAGE_MAX_BYTES + 1),
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === "INVALID_INPUT" &&
        error.details?.maxBytes === COVER_IMAGE_MAX_BYTES,
    );
  });

  it("rejects empty files", () => {
    assert.throws(
      () => validateCoverImage("image/png", 0),
      (error: unknown) =>
        error instanceof ApiError && error.code === "INVALID_INPUT",
    );
  });

  it("builds storage key and public URL", () => {
    const key = buildCoverImageKey(EVENT_ID, FILE_ID, "png");
    assert.equal(key, `${EVENT_ID}/${FILE_ID}.png`);
    assert.equal(
      buildCoverImageUrl(key),
      `/api/v1/media/events/${EVENT_ID}/${FILE_ID}.png`,
    );
  });
});
