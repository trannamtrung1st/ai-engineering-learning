export const WEB_BASE_URL =
  process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3007";
export const API_BASE_URL =
  process.env.PLAYWRIGHT_API_BASE_URL ?? "http://localhost:3001/api/v1";

/** Matches scripts/db-seed.mjs TEST_PASSWORD_HASH (attendly-test-password). */
export const DEFAULT_PASSWORD = "attendly-test-password";
