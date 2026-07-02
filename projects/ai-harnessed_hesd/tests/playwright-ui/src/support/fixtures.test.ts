import { describe, expect, it } from "vitest";
import { LECTURER_PERSONA, SEED_FIXTURE_IDS, STUDENT_PERSONA } from "./fixtures.js";
import { DEFAULT_PASSWORD } from "./constants.js";

/**
 * AC-01, AC-11, AC-16, NFR-14 — seed-aligned smoke persona fixtures for Playwright UI regression.
 */
describe("playwright-ui smoke personas", () => {
  it("AC-01 lecturer persona matches seed lecturer email", () => {
    expect(LECTURER_PERSONA.role).toBe("lecturer");
    expect(LECTURER_PERSONA.email).toBe("lecturer@attendly.local");
    expect(LECTURER_PERSONA.viewport.width).toBeGreaterThanOrEqual(1280);
  });

  it("AC-11 NFR-14 student persona uses mobile viewport and seed student email", () => {
    expect(STUDENT_PERSONA.role).toBe("student");
    expect(STUDENT_PERSONA.email).toBe("student1@attendly.local");
    expect(STUDENT_PERSONA.viewport.width).toBeLessThanOrEqual(375);
    expect(STUDENT_PERSONA.homePath).toBe("/check-in");
  });

  it("AC-16 personas share deterministic test password from local setup docs", () => {
    expect(LECTURER_PERSONA.password).toBe(DEFAULT_PASSWORD);
    expect(STUDENT_PERSONA.password).toBe(DEFAULT_PASSWORD);
  });

  it("NFR-14 seed fixture IDs stay stable for preview stack smoke data", () => {
    expect(SEED_FIXTURE_IDS.lecturerUser).toMatch(
      /^60000000-0000-4000-8000-/,
    );
    expect(SEED_FIXTURE_IDS.openSession).not.toBe(SEED_FIXTURE_IDS.scheduledSession);
  });
});
