/**
 * Shared domain package — enums, validators, and error identifiers.
 *
 * Framework-agnostic exports shared by API and web workspaces.
 */

export const DOMAIN_PACKAGE_VERSION = "0.0.1";

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
