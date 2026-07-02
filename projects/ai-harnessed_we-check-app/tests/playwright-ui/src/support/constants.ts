export const WEB_BASE_URL =
  process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3007";
export const API_BASE_URL =
  process.env.PLAYWRIGHT_API_BASE_URL ?? "http://localhost:3001/api/v1";

export const DEFAULT_PASSWORD = "TestPass123";
export const ADMIN_PASSWORD = "AdminPass123";

/** Preview seed accounts — apps/api/src/infra/preview-seed.ts */
export const PREVIEW_CREDENTIALS = {
  student: { email: "student@example.edu.vn", password: "StudentPass8" },
  instructor: { email: "instructor@example.edu.vn", password: "InstructorPass8" },
  admin: { email: "admin@example.edu.vn", password: "AdminPass123" },
} as const;

export const PREVIEW_TOKEN_ALIASES = {
  stale: "stale-token-id",
  valid: "valid-token-id",
} as const;
