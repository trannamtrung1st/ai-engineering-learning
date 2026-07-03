/**
 * Traceability: FR-27 FR-28 BR-18 BR-19 AC-15 AC-16 AC-17
 */
import { describe, expect, it } from "vitest";
import { parseReportQuery, validateExportBody } from "./validation.js";

describe("M07 report/export validation — FR-28 VR-RP-01", () => {
  it("TC-FR-28-014: rejects unknown report filter keys with InvalidFilter", () => {
    const parsed = parseReportQuery({
      termId: "20000000-0000-4000-8000-000000000001",
      unknownFilter: "foo",
    });
    expect(parsed.error?.code).toBe("InvalidFilter");
  });

  it("TC-FR-28-003: rejects unsupported sortBy values", () => {
    const parsed = parseReportQuery({
      termId: "20000000-0000-4000-8000-000000000001",
      sortBy: "studentName",
    });
    expect(parsed.error?.code).toBe("InvalidFilter");
  });

  it("TC-FR-28-015: rejects pageSize above 100", () => {
    const parsed = parseReportQuery({
      termId: "20000000-0000-4000-8000-000000000001",
      pageSize: "101",
    });
    expect(parsed.error?.code).toBe("InvalidPayload");
  });

  it("TC-FR-28-003: rejects malformed UUID classSectionId", () => {
    const parsed = parseReportQuery({
      classSectionId: "not-a-uuid",
    });
    expect(parsed.error?.code).toBe("InvalidFilter");
  });

  it("TC-FR-27-012: rejects unsupported export format with UnsupportedFormat", () => {
    const result = validateExportBody({
      format: "xlsx",
      filters: { termId: "20000000-0000-4000-8000-000000000001" },
    });
    expect(result.error?.code).toBe("UnsupportedFormat");
  });

  it("accepts allow-listed filters and pagination defaults", () => {
    const parsed = parseReportQuery({
      termId: "20000000-0000-4000-8000-000000000001",
      status: "Absent",
      sortBy: "date",
      sortOrder: "desc",
    });
    expect(parsed.error).toBeNull();
    expect(parsed.page).toBe(1);
    expect(parsed.pageSize).toBe(25);
    expect(parsed.filters.status).toBe("Absent");
  });
});
