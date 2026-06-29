import { AttendanceStatus } from "@wecheck/domain";
import { describe, expect, it } from "vitest";
import type { SessionMonitorRecord } from "@/lib/session-monitor-api";
import {
  filterMonitorRecords,
  sortMonitorRecords,
  STATUS_SORT_ORDER,
} from "@/lib/session-monitor-roster";

const records: SessionMonitorRecord[] = [
  {
    id: "1",
    studentId: "a",
    institutionalId: "SV1",
    displayName: "Zeta",
    status: AttendanceStatus.Present,
    checkedInAt: null,
  },
  {
    id: "2",
    studentId: "b",
    institutionalId: "SV2",
    displayName: "Alpha",
    status: AttendanceStatus.Pending,
    checkedInAt: null,
  },
  {
    id: "3",
    studentId: "c",
    institutionalId: "SV3",
    displayName: "Beta",
    status: AttendanceStatus.Absent,
    checkedInAt: null,
  },
];

/** AC-15b — roster sort/filter helpers */
describe("session-monitor-roster (AC-15, FR-15)", () => {
  it("TC-AC-15-009: status sort order Pending before Absent before Present", () => {
    const sorted = sortMonitorRecords(records, "status", "asc");
    expect(sorted.map((r) => r.status)).toEqual([
      AttendanceStatus.Pending,
      AttendanceStatus.Absent,
      AttendanceStatus.Present,
    ]);
    expect(STATUS_SORT_ORDER[AttendanceStatus.Pending]).toBeLessThan(
      STATUS_SORT_ORDER[AttendanceStatus.Present]!,
    );
  });

  it("TC-AC-15-013: filterMonitorRecords scopes to Present only", () => {
    const filtered = filterMonitorRecords(records, AttendanceStatus.Present);
    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.institutionalId).toBe("SV1");
  });
});
