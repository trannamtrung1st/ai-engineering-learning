import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  QR_TOKEN_TTL_MS,
  computeTokenExpiresAt,
  isQrTokenExpired,
  qrTokenRemainingMs,
} from "@wecheck/domain";

/**
 * Traceability: AC-06 AC-07 FR-06 FR-07 BR-03 NFR-06
 * Cases: TC-AC-06-001 TC-AC-06-002 TC-BR-03-003
 */
describe("QR token expiry (AC-06, BR-03, FR-06, NFR-06)", () => {
  const issuedAt = new Date("2026-06-28T08:05:00.000Z");

  it("expires_at equals issued_at + 30 seconds (TC-AC-06-001, BR-03)", () => {
    const expiresAt = computeTokenExpiresAt(issuedAt);
    assert.equal(
      expiresAt.getTime() - issuedAt.getTime(),
      QR_TOKEN_TTL_MS,
    );
  });

  it("token valid at exactly T + 30 s inclusive boundary (TC-BR-03-003)", () => {
    const atBoundary = new Date(issuedAt.getTime() + QR_TOKEN_TTL_MS);
    assert.equal(isQrTokenExpired(issuedAt, atBoundary), false);
  });

  it("token expired at T + 31 seconds (TC-AC-06-002, AC-06b)", () => {
    const afterExpiry = new Date(issuedAt.getTime() + QR_TOKEN_TTL_MS + 1000);
    assert.equal(isQrTokenExpired(issuedAt, afterExpiry), true);
  });

  it("secondsRemaining within 29-30 at issuance (NFR-06)", () => {
    const remaining = qrTokenRemainingMs(issuedAt, issuedAt);
    const seconds = Math.ceil(remaining / 1000);
    assert.ok(seconds >= 29 && seconds <= 30);
  });
});
