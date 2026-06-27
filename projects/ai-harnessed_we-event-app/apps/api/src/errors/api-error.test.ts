import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ApiError, buildErrorEnvelope } from "./api-error.js";

describe("api error envelope", () => {
  it("builds standard error shape with requestId and timestamp", () => {
    const envelope = buildErrorEnvelope(
      "UNAUTHENTICATED",
      "Authentication required.",
      "req-123",
      { field: "token" },
    );

    assert.equal(envelope.error.code, "UNAUTHENTICATED");
    assert.equal(envelope.error.message, "Authentication required.");
    assert.equal(envelope.error.requestId, "req-123");
    assert.deepEqual(envelope.error.details, { field: "token" });
    assert.match(envelope.error.timestamp, /^\d{4}-\d{2}-\d{2}T/);
  });

  it("ApiError carries code, status, and details", () => {
    const error = new ApiError({
      code: "FORBIDDEN",
      message: "Denied.",
      statusCode: 403,
      details: { role: "Participant" },
    });

    assert.equal(error.code, "FORBIDDEN");
    assert.equal(error.statusCode, 403);
    assert.deepEqual(error.details, { role: "Participant" });
  });
});
