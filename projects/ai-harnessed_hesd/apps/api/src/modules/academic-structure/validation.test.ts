/**
 * Traceability: FR-01 FR-04 FR-06 BR-06 AC-07
 * TC-FR-01-009 TC-FR-04-003 TC-FR-06-001
 */
import { describe, expect, it } from "vitest";
import {
  datesForDayOfWeek,
  isUuid,
  sessionTimesForDate,
  validateScheduleTemplate,
  validateTermDates,
} from "./validation.js";

describe("academic structure validation — FR-01 FR-04 FR-06 BR-06", () => {
  it("TC-FR-01-009: rejects endDate before startDate", () => {
    expect(validateTermDates("2026-12-31", "2026-08-01")).toBe(false);
    expect(validateTermDates("2026-08-01", "2026-12-31")).toBe(true);
  });

  it("validates schedule template shape for section session generation (FR-06)", () => {
    expect(
      validateScheduleTemplate({
        dayOfWeek: "Monday",
        startTime: "08:00",
        durationMinutes: 120,
      }),
    ).toBeNull();
    expect(
      validateScheduleTemplate({
        dayOfWeek: "NotADay",
        startTime: "08:00",
        durationMinutes: 120,
      }),
    ).toBeTruthy();
  });

  it("generates weekly session dates within term bounds (FR-06)", () => {
    const dates = datesForDayOfWeek("2026-01-05", "2026-01-26", "Monday");
    expect(dates).toEqual(["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]);
  });

  it("derives scheduled end from duration (FR-06)", () => {
    const { scheduledStartAt, scheduledEndAt } = sessionTimesForDate(
      "2026-07-02",
      "08:00",
      120,
    );
    expect(scheduledEndAt.getTime() - scheduledStartAt.getTime()).toBe(120 * 60_000);
  });

  it("isUuid accepts RFC4122 identifiers", () => {
    expect(isUuid("20000000-0000-4000-8000-000000000001")).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
  });
});
