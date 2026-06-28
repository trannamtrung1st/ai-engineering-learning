/**
 * Shared domain package — enums, state machines, geo helpers, validation identifiers.
 *
 * Framework-agnostic exports shared by API and web workspaces.
 * @see docs/technical/03-domain-model.md
 */

export const DOMAIN_PACKAGE_VERSION = "0.1.0";

/** VAL-03 / NFR-14 password policy bounds for local accounts. */
export const PASSWORD_POLICY = {
  MIN_LENGTH: 8,
  MAX_LENGTH: 128,
} as const;

export const NON_FUNCTIONAL_REQUIREMENT_IDS = {
  NFR_14: "NFR-14",
} as const;

export function isPasswordLengthValid(length: number): boolean {
  return (
    length >= PASSWORD_POLICY.MIN_LENGTH &&
    length <= PASSWORD_POLICY.MAX_LENGTH
  );
}

export * from "./enums.js";
export * from "./constants.js";
export * from "./validation/rule-ids.js";
export * from "./geo/haversine.js";
export * from "./session/state-guard.js";
export * from "./session/attendance-window.js";
export * from "./qr/token-expiry.js";
export * from "./attendance/duplicate-check.js";
export * from "./attendance/edit-window.js";
