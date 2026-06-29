import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { AttendanceStatus } from "@wecheck/domain";
import {
  CSV_HEADERS,
  exportFilename,
  formatAttendanceCsv,
} from "./csv-formatter.js";

/**
 * Traceability: AC-13 FR-13 BR-09 NFR-07
 * Cases: TC-AC-13-001 TC-AC-13-003 TC-FR-13-003 TC-FR-13-005
 */
describe("csv-formatter (AC-13, FR-13, BR-09, NFR-07)", () => {
  it("TC-AC-13-003: CSV header columns match API design §8.3", () => {
    assert.deepEqual(CSV_HEADERS, [
      "institutional_id",
      "display_name",
      "class_code",
      "subject_code",
      "session_date",
      "attendance_status",
      "checked_in_at",
    ]);
    const csv = formatAttendanceCsv([]);
    assert.equal(csv.split("\n")[0], CSV_HEADERS.join(","));
  });

  it("TC-FR-13-003: formats rows with UTF-8 Vietnamese names and empty checked_in_at", () => {
    const csv = formatAttendanceCsv([
      {
        institutionalId: "SV2026001",
        displayName: "Nguyễn Văn A",
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        sessionDate: "2026-06-15",
        attendanceStatus: AttendanceStatus.Present,
        checkedInAt: "2026-06-15T08:05:12.000Z",
      },
      {
        institutionalId: "SV2026002",
        displayName: "Trần, Thị B",
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        sessionDate: "2026-06-15",
        attendanceStatus: AttendanceStatus.Absent,
        checkedInAt: null,
      },
    ]);

    const lines = csv.trimEnd().split("\n");
    assert.equal(lines.length, 3);
    assert.match(lines[1]!, /SV2026001,Nguyễn Văn A,HESD-01,SWE-101,2026-06-15,Present,2026-06-15T08:05:12.000Z/);
    assert.match(lines[2]!, /SV2026002,"Trần, Thị B"/);
    assert.match(lines[2]!, /Absent,$/);
  });

  it("TC-AC-13-005: exportFilename uses attendance-export-YYYY-MM-DD pattern", () => {
    assert.equal(
      exportFilename(new Date("2026-06-28T12:00:00.000Z")),
      "attendance-export-2026-06-28.csv",
    );
  });
});
