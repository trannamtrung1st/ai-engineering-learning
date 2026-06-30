import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ErrorCode } from "@wecheck/domain";
import {
  preflightFailureMessage,
  preflightHttpStatus,
  SESSION_MISMATCH_CODE,
} from "./preflight-response.js";

/**
 * Traceability: AC-07 FR-07 BR-03 BR-11 BR-15
 */
describe("preflight response helpers (AC-07, FR-07, BR-15)", () => {
  it("maps preflight error codes to HTTP status per API design §6.2 (TC-BR-15-007)", () => {
    assert.equal(preflightHttpStatus(ErrorCode.TokenNotFound), 404);
    assert.equal(preflightHttpStatus(ErrorCode.ExpiredQr), 403);
    assert.equal(preflightHttpStatus(ErrorCode.SessionNotActive), 403);
    assert.equal(preflightHttpStatus(ErrorCode.NotEnrolled), 403);
    assert.equal(preflightHttpStatus(ErrorCode.TokenAlreadyUsed), 403);
    assert.equal(preflightHttpStatus(SESSION_MISMATCH_CODE), 403);
  });

  it("returns Vietnamese messages for preflight failures (TC-AC-07-018, BR-03)", () => {
    assert.equal(
      preflightFailureMessage(ErrorCode.ExpiredQr),
      "Mã QR đã hết hạn, vui lòng quét mã mới",
    );
    assert.equal(
      preflightFailureMessage(ErrorCode.NotEnrolled),
      "Bạn không thuộc danh sách lớp của buổi học này",
    );
    assert.equal(
      preflightFailureMessage(ErrorCode.TokenAlreadyUsed),
      "Mã QR đã được sử dụng",
    );
    assert.equal(
      preflightFailureMessage(SESSION_MISMATCH_CODE),
      "Mã QR không khớp với buổi học",
    );
    assert.equal(
      preflightFailureMessage(ErrorCode.TokenNotFound),
      "Mã QR không hợp lệ",
    );
  });
});
