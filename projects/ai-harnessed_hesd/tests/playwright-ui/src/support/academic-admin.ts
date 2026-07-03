import type { Page } from "@playwright/test";
import { loginViaApi } from "./auth.js";
import { DEFAULT_PASSWORD } from "./constants.js";

export const ACADEMIC_ADMIN_EMAIL = "academic-admin@attendly.local";

/** Authenticate AcademicAdmin for PG-07/PG-09/PG-10 admin setup routes. */
export async function loginAcademicAdmin(
  page: Page,
  afterLoginPath = "/admin/terms",
): Promise<void> {
  await loginViaApi(page, ACADEMIC_ADMIN_EMAIL, DEFAULT_PASSWORD, afterLoginPath);
}

/** Mixed CSV rows for FR-04 enrollment import browser journeys. */
export function buildMixedEnrollmentCsv(): string {
  return ["studentCode", "SV001", "SV002", "FAKE999", "SV001"].join("\n");
}

/** Unique term code for idempotent create flows in regression runs. */
export function uniqueTermCode(prefix = "2026-bt"): string {
  const suffix = Date.now().toString(36).slice(-4);
  return `${prefix}-${suffix}`;
}

/** Unique section code for idempotent FRM-04 create flows. */
export function uniqueSectionCode(prefix = "SE101-BT"): string {
  const suffix = Date.now().toString(36).slice(-4).toUpperCase();
  return `${prefix}-${suffix}`;
}
