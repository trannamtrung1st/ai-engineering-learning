import { describe, expect, it } from "vitest";
import { groupRowsBySection, type AttendanceHistoryRow } from "./attendance-history-api.js";

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
});
