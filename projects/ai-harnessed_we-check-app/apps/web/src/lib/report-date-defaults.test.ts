import { describe, expect, it } from "vitest";
import {
  formatAttendanceRate,
  formatReportDateVi,
  sessionDateInRange,
} from "@/lib/report-date-defaults";

/** FR-12 / AC-12 — report date helpers */
describe("report-date-defaults (FR-12, AC-12)", () => {
  it("TC-AC-12-011: formats ISO session dates for vi-VN table display", () => {
    expect(formatReportDateVi("2026-06-28T10:00:00.000Z")).toBe("28/06/2026");
  });

  it("TC-FR-12-011: filters sessions within inclusive date range", () => {
    expect(sessionDateInRange("2026-06-15T08:00:00.000Z", "2026-06-01", "2026-06-30")).toBe(
      true,
    );
    expect(sessionDateInRange("2026-05-31T08:00:00.000Z", "2026-06-01", "2026-06-30")).toBe(
      false,
    );
  });

  it("TC-BR-08-011: formats attendance rate as whole-percent string", () => {
    expect(formatAttendanceRate(0.875)).toBe("88%");
    expect(formatAttendanceRate(0)).toBe("0%");
  });
});
