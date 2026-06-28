import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";
import { ErrorCode } from "@wecheck/domain";
import {
  ApiError,
  ERROR_MESSAGES,
  forbidden,
  sessionExpired,
  unauthenticated,
} from "./api-error.js";

/**
 * Traceability: NFR-10 FR-02 NFR-16
 */
describe("api-error envelope (NFR-10, FR-02)", () => {
  it("builds standard error body with requestId (TC-NFR-10-004)", () => {
    const error = unauthenticated();
    const body = error.toBody("550e8400-e29b-41d4-a716-446655440000");
    assert.equal(body.errorCode, ErrorCode.Unauthenticated);
    assert.equal(body.message, ERROR_MESSAGES[ErrorCode.Unauthenticated]);
    assert.equal(body.requestId, "550e8400-e29b-41d4-a716-446655440000");
  });

  it("maps SessionExpired to 401 with Vietnamese message (NFR-16, TC-NFR-16-005)", () => {
    const error = sessionExpired();
    assert.equal(error.statusCode, 401);
    assert.equal(error.errorCode, ErrorCode.SessionExpired);
    assert.equal(error.message, "Phiên đăng nhập đã hết hạn");
  });

  it("maps Forbidden to 403 (NFR-11)", () => {
    const error = forbidden();
    assert.equal(error.statusCode, 403);
    assert.equal(error.errorCode, ErrorCode.Forbidden);
  });

  it("includes optional validation details", () => {
    const error = new ApiError(422, ErrorCode.ValidationFailed, "Dữ liệu không hợp lệ", [
      { field: "email", code: "InvalidEmail", message: "Email không hợp lệ" },
    ]);
    const body = error.toBody(randomUUID());
    assert.deepEqual(body.details, [
      { field: "email", code: "InvalidEmail", message: "Email không hợp lệ" },
    ]);
  });
});
