import { describe, expect, it } from "vitest";
import type { RosterRow } from "../api/roster-api";
import { filterAndSortRosterRows } from "./roster-list-query";

/** Traceability: FR-19 */
describe("roster-list-query — FR-19", () => {
  const rows: RosterRow[] = [
    {
      studentUserId: "1",
      studentCode: "SV001",
      displayName: "An",
      attendanceStatus: "Pending",
      checkInMethod: null,
      checkInAt: null,
      latestAttemptOutcome: "OutOfRadius",
    },
    {
      studentUserId: "2",
      studentCode: "SV002",
      displayName: "Bình",
      attendanceStatus: "Present",
      checkInMethod: "QR",
      checkInAt: "2026-07-02T08:00:00Z",
      latestAttemptOutcome: "Success",
    },
    {
      studentUserId: "3",
      studentCode: "SV003",
      displayName: "Chi",
      attendanceStatus: "Absent",
      checkInMethod: null,
      checkInAt: null,
      latestAttemptOutcome: null,
    },
  ];

  it("filters by attemptOutcome for rejected rows", () => {
    const filtered = filterAndSortRosterRows(rows, {
      attemptOutcome: "OutOfRadius",
      sortBy: "status",
      sortOrder: "asc",
    });
    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.studentCode).toBe("SV001");
  });

  it("groups checked-in students before pending and absent", () => {
    const sorted = filterAndSortRosterRows(rows, { sortBy: "status", sortOrder: "asc" });
    expect(sorted[0]?.attendanceStatus).toBe("Present");
    expect(sorted[sorted.length - 1]?.attendanceStatus).toBe("Absent");
  });
});
