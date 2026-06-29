import { describe, expect, it } from "vitest";
import { parseReportFiltersFromSearchParams } from "@/lib/report-filter-url";

/** AC-12 / BR-08 — deep-link report filter parsing */
describe("parseReportFiltersFromSearchParams (AC-12, BR-08)", () => {
  it("TC-AC-12-013: parses classCode and subjectCode from reports URL", () => {
    const params = new URLSearchParams(
      "classCode=HESD-01&subjectCode=SWE-101&from=2026-06-01&to=2026-06-30",
    );
    expect(parseReportFiltersFromSearchParams(params)).toEqual({
      classCode: "HESD-01",
      subjectCode: "SWE-101",
      from: "2026-06-01",
      to: "2026-06-30",
    });
  });

  it("returns null when class or subject is missing", () => {
    expect(parseReportFiltersFromSearchParams(new URLSearchParams("classCode=HESD-01"))).toBeNull();
  });
});
