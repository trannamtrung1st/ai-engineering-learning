/**
 * Traceability: FR-04
 * TC-FR-04-010
 */
import { describe, expect, it } from "vitest";
import { parseEnrollmentCsv } from "./academic-api";

describe("parseEnrollmentCsv (FR-04)", () => {
  it("TC-FR-04-010: parses studentCode header and data rows", () => {
    const csv = "studentCode\nSV001\nSV002\n";
    expect(parseEnrollmentCsv(csv)).toEqual([
      { studentCode: "SV001" },
      { studentCode: "SV002" },
    ]);
  });

  it("parses single-column CSV without header", () => {
    expect(parseEnrollmentCsv("SV003\nSV004")).toEqual([
      { studentCode: "SV003" },
      { studentCode: "SV004" },
    ]);
  });
});
