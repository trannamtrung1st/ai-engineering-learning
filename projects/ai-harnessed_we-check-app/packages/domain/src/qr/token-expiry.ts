import { QR_TOKEN_TTL_MS } from "../constants.js";

/** BR-03 — expires_at = issued_at + 30 seconds. */
export function computeTokenExpiresAt(issuedAt: Date): Date {
  return new Date(issuedAt.getTime() + QR_TOKEN_TTL_MS);
}

/**
 * BR-03 — token expired when now > issuedAt + 30 s (inclusive at boundary).
 * Check-in at exactly T + 30 s is still valid.
 */
export function isQrTokenExpired(issuedAt: Date, now: Date): boolean {
  return now.getTime() > issuedAt.getTime() + QR_TOKEN_TTL_MS;
}

/** Remaining validity in milliseconds (0 when expired). */
export function qrTokenRemainingMs(issuedAt: Date, now: Date): number {
  const remaining = issuedAt.getTime() + QR_TOKEN_TTL_MS - now.getTime();
  return Math.max(0, remaining);
}
