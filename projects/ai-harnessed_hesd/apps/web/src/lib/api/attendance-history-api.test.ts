import { describe, expect, it } from "vitest";
import {
  buildSectionFilterOptions,
  groupRowsBySection,
  type AttendanceHistoryRow,
} from "./attendance-history-api.js";

/** Traceability: FR-37 */
describe("attendance-history-api — FR-37", () => {
  it("groups history rows by section code for PG-03 layout", () => {
    const rows: AttendanceHistoryRow[] = [
      {
        attendanceRecordId: "1",
        studentUserId: "s1",
        studentCode: "SV001",
        classSessionId: "sess-1",
        classSectionId: "sec-a",
        sectionCode: "SE101-01",
        attendanceStatus: "Present",
        checkInAt: "2026-02-01T08:05:00Z",
        checkInMethod: "QR",
        sessionDate: "2026-02-01",
      },
      {
        attendanceRecordId: "2",
        studentUserId: "s1",
        studentCode: "SV001",
        classSessionId: "sess-2",
        classSectionId: "sec-b",
        sectionCode: "SE102-01",
        attendanceStatus: "Absent",
        checkInAt: null,
        checkInMethod: null,
        sessionDate: "2026-02-02",
      },
    ];

    const groups = groupRowsBySection(rows);
    expect(groups.size).toBe(2);
    expect(groups.get("SE101-01")).toHaveLength(1);
    expect(groups.get("SE102-01")?.[0]?.attendanceStatus).toBe("Absent");
  });

  it("TC-UX-COMMON-006: section filter labels use section codes not UUID fragments", () => {
    const rows: AttendanceHistoryRow[] = [
      {
        attendanceRecordId: "1",
        studentUserId: "s1",
        studentCode: "SV001",
        classSessionId: "sess-1",
        classSectionId: "93947384-0000-4000-8000-000000000099",
        sectionCode: "SE101-01",
        attendanceStatus: "Present",
        checkInAt: "2026-02-01T08:05:00Z",
        checkInMethod: "QR",
        sessionDate: "2026-02-01",
      },
    ];

    const options = buildSectionFilterOptions(
      ["93947384-0000-4000-8000-000000000099", "f0e41570-0000-4000-8000-000000000088"],
      rows,
    );

    expect(options[0]?.label).toBe("SE101-01");
    expect(options[1]?.label).toBe("Lớp đã ghi danh");
    expect(options.every((option) => !/^[0-9a-f]{8}$/i.test(option.label))).toBe(true);
  });
});
