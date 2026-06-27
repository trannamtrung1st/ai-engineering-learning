import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ALLOWED_COVER_IMAGE_MIME_TYPES,
  COVER_IMAGE_MAX_BYTES,
  validateCoverImageFile,
} from "./cover-image.js";

describe("cover-image validation", () => {
  it("FR-35 / AC-17: accepts JPEG, PNG, and WebP under 5 MB", () => {
    for (const type of ALLOWED_COVER_IMAGE_MIME_TYPES) {
      const file = new File(["x"], "cover.bin", { type });
      Object.defineProperty(file, "size", { value: COVER_IMAGE_MAX_BYTES });
      assert.equal(validateCoverImageFile(file), null);
    }
  });

  it("FR-35: rejects disallowed MIME types", () => {
    const file = new File(["x"], "cover.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: 1024 });
    assert.match(validateCoverImageFile(file)!, /JPEG, PNG, or WebP/);
  });

  it("FR-35 / NFR-18: rejects files over 5 MB", () => {
    const file = new File(["x"], "cover.png", { type: "image/png" });
    Object.defineProperty(file, "size", { value: COVER_IMAGE_MAX_BYTES + 1 });
    assert.match(validateCoverImageFile(file)!, /5 MB/);
  });
});
